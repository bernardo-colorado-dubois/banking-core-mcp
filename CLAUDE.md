# Banking core MCP

Servidor MCP (FastMCP) que expone la API HTTP del core bancario de `../banking-core` como herramientas. No tiene reglas de negocio propias: cada tool envuelve un endpoint del core y actúa con los permisos del usuario que inició sesión. El RBAC, la partida doble, las invariantes y el bloqueo de filas viven en el core. Cómo funciona por dentro está en `README.md`; las rutas y reglas del core, en `../banking-core/CLAUDE.md`.

## Comandos

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python main.py                                                    # arranca el servidor por stdio (lo hace el cliente MCP, no a mano)
venv/bin/fastmcp list --command "venv/bin/python main.py"                  # lista las tools
venv/bin/fastmcp call --command "venv/bin/python main.py" --target whoami  # llama una tool; argumentos como key=value o --input-json
venv/bin/fastmcp dev inspector main.py                                     # MCP Inspector en el navegador
```

- El core tiene que estar corriendo (`make up` en `../banking-core`, `http://localhost:8080`). Si no, toda tool devuelve `[503] Cannot reach the banking core ...`.
- No hay tests. Una tool se verifica con `fastmcp call` contra el core levantado. Las tools de escritura mueven dinero real en la BD de desarrollo: para probar, usar primero las de solo lectura (`whoami`, `list_accounts`, `get_account_movements`).
- El servidor está registrado en Claude Code a nivel usuario como `banking-core`. Un cambio en `main.py` o `banking_client.py` solo se ve tras reiniciar el servidor MCP (`/mcp` o una sesión nueva).
- Las dependencias directas están fijadas en `requirements.txt`; tras cambiarlo, `venv/bin/pip install -r requirements.txt`. El cliente HTTP es `httpx2`, que se importa como `import httpx2 as httpx`.

## Variables de entorno

Se cargan de `.env` junto a `main.py` (ruta absoluta, no depende del directorio de trabajo). `.env` no se versiona; se crea copiando `.env.example`.

| Variable | Uso |
|---|---|
| `BANKING_API_URL` | URL del core, `http://localhost:8080` por defecto |
| `BANKING_EMAIL`, `BANKING_PASSWORD` | Usuario con el que el servidor inicia sesión. Opcionales: sin ellas hay que llamar a la tool `login` primero |

- Por decisión del usuario, el MCP inicia sesión como el **admin** del core.
- El `ADMIN_PASSWORD` de `../banking-core/.env` es solo la contraseña inicial de la semilla: el admin ya la cambió, así que copiarla da `401 Invalid credentials`. Ante un 401 al iniciar sesión, pedir al usuario que actualice `BANKING_PASSWORD` en este `.env`; no copiarla del core.

## Estructura

```
main.py              # servidor FastMCP: instructions, anotaciones, tipos de argumentos y las 17 tools
banking_client.py    # BankingClient (httpx async): sesión JWT, re-login en 401, BankingError
requirements.txt
.env.example
README.md            # documentación pública, en inglés
img/                 # imágenes de LinkedIn y del README (2160x2700); img/src tiene los HTML de origen
```

## Cómo agregar una tool

Si el core agrega un endpoint, se expone en dos pasos:

1. **`banking_client.py`**: un método async en la sección del módulo (`# --- user`, `# --- account`) que solo llama a `self.request(método, ruta, cuerpo)` y devuelve el dict. Sin validaciones ni lógica.
2. **`main.py`**: una función con `@mcp.tool(annotations=...)` en la sección que corresponda (`# --- session`, `users`, `accounts`, `operations`), cuyo cuerpo es `return await call(client.<método>(...))`.

Reglas para la tool:

- **El docstring es la descripción que ve el modelo.** Una o dos frases en inglés: qué hace, quién puede hacerlo si está restringido (`(admin only)`) y qué devuelve.
- **Argumentos:** cada uno con `Annotated[tipo, Field(description=...)]`. Se reutilizan los alias `Amount`, `Email`, `Password` y `Alias`. Los ids se tipan como `UUID` y se pasan al cliente con `str(...)`. Los montos con `Amount` y se mandan con `.strip()`.
- **Anotaciones:** `READ_ONLY` para consultas, `WRITE` para lo que crea o modifica sin pérdida, `DESTRUCTIVE` para lo que mueve dinero hacia afuera, revierte o quita acceso (retiro, transferencia, reverso, desactivación). El depósito es `WRITE`.
- **Siempre `call(...)`**: convierte `BankingError` en `ToolError("[status] mensaje")`, para que el modelo vea el mensaje real del core.
- Al agregar o quitar una tool, actualizar las tablas de `README.md` y el conteo de 17 (README e imágenes 01 y 02).

## Sesión

- `BankingClient` inicia sesión en la primera llamada, no al arrancar. `request()` reintenta **una vez** tras un 401 iniciando sesión de nuevo, solo si tiene contraseña guardada.
- `login` reemplaza las credenciales guardadas: las tools siguientes (y el re-login automático) usan al nuevo usuario. `change_password` actualiza la contraseña guardada, pero no `.env`.
- `claims()` decodifica el payload del JWT **sin verificar la firma**: solo para leer `sub` y `role`. Nunca se usa para autorizar; eso lo hace el core.
- Los errores de red se convierten en `BankingError(503, ...)`. El timeout es de 15 s.

## Convenciones

- Indentación de 2 espacios, comillas simples.
- Idioma: código, docstrings, `instructions` del servidor, mensajes de error y `README.md` en **inglés**. Este archivo sigue en español, igual que el del core.
- Montos siempre como `str` con 2 decimales como máximo, validados por el patrón de `Amount`. Nunca `float`.
- Nada de reglas de negocio en el MCP: si el core rechaza algo, el error se devuelve tal cual. No se duplican validaciones del core (saldo, permisos, cuentas activas).
- El proyecto es un repositorio git con una sola rama, `main`, sin remoto. `.env`, `venv/` y `__pycache__/` están en `.gitignore`.
