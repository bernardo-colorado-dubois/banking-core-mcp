"""HTTP client for the banking core API (../banking-core).

Handles the JWT session: logs in with email and password, keeps the token
and logs in again once when the core answers 401 (expired token).
"""
import base64
import json
from typing import Any

import httpx2 as httpx


class BankingError(Exception):
  """Error returned by the core: the message is the `error` field of its JSON."""

  def __init__(self, status: int, message: str) -> None:
    super().__init__(message)
    self.status = status


class BankingClient:
  def __init__(self, base_url: str, email: str | None = None, password: str | None = None, timeout: float = 15.0) -> None:
    self.base_url = base_url.rstrip('/')
    self.email = email
    self.password = password
    self.token: str | None = None
    self.must_change_password = False
    self.http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

  async def close(self) -> None:
    await self.http.aclose()

  # --- session -------------------------------------------------------------

  async def login(self, email: str | None = None, password: str | None = None) -> dict:
    """Logs in and keeps the token. Without arguments it uses the stored credentials."""
    if email is not None:
      self.email, self.password = email, password
    if not self.email or not self.password:
      raise BankingError(401, 'No credentials: set BANKING_EMAIL and BANKING_PASSWORD or call the login tool')

    data = await self._send('POST', '/user/login', json={'email': self.email, 'password': self.password}, auth=False)
    self.token = data['token']
    self.must_change_password = data.get('must_change_password', False)
    return data

  def claims(self) -> dict:
    """Token payload (sub, role, exp) without verifying the signature: only informative."""
    if not self.token:
      return {}
    payload = self.token.split('.')[1]
    payload += '=' * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))

  async def request(self, method: str, path: str, json: Any = None) -> dict:
    """Authenticated call. Logs in if there is no token and retries once on 401."""
    if self.token is None:
      await self.login()
    try:
      return await self._send(method, path, json=json)
    except BankingError as error:
      if error.status != 401 or not self.password:
        raise
    await self.login()
    return await self._send(method, path, json=json)

  async def _send(self, method: str, path: str, json: Any = None, auth: bool = True) -> dict:
    headers = {'Authorization': f'Bearer {self.token}'} if auth and self.token else {}
    try:
      response = await self.http.request(method, path, json=json, headers=headers)
    except httpx.HTTPError as error:
      raise BankingError(503, f'Cannot reach the banking core at {self.base_url}: {error}') from error

    try:
      data = response.json()
    except ValueError:
      data = {}
    if response.is_error:
      message = data.get('error') if isinstance(data, dict) else None
      raise BankingError(response.status_code, message or f'Request failed with status {response.status_code}')
    return data

  # --- user ------------------------------------------------------------------

  async def change_password(self, current_password: str, new_password: str) -> dict:
    data = await self.request('POST', '/user/password', {'current_password': current_password, 'new_password': new_password})
    self.password = new_password
    self.must_change_password = False
    return data

  async def user_profile(self, user_id: str) -> dict:
    return await self.request('GET', f'/user/{user_id}')

  async def list_users(self) -> dict:
    return await self.request('GET', '/user/')

  async def signup_admin(self, email: str, password: str) -> dict:
    return await self.request('POST', '/user/admin', {'email': email, 'password': password})

  async def signup_operator(self, email: str, password: str) -> dict:
    return await self.request('POST', '/user/operator', {'email': email, 'password': password})

  async def deactivate_user(self, email: str) -> dict:
    return await self.request('POST', '/user/deactivate', {'email': email})

  # --- account ---------------------------------------------------------------

  async def list_accounts(self) -> dict:
    return await self.request('GET', '/account/')

  async def signup_client(self, email: str, password: str, name: str, alias: str) -> dict:
    return await self.request('POST', '/account/client', {'email': email, 'password': password, 'name': name, 'alias': alias})

  async def open_vostro(self, email: str, alias: str) -> dict:
    return await self.request('POST', '/account/vostro', {'email': email, 'alias': alias})

  async def open_nostro(self, alias: str) -> dict:
    return await self.request('POST', '/account/nostro', {'alias': alias})

  async def deposit(self, account_id: str, amount: str) -> dict:
    return await self.request('POST', f'/account/{account_id}/deposit', {'amount': amount})

  async def withdraw(self, account_id: str, amount: str) -> dict:
    return await self.request('POST', f'/account/{account_id}/withdrawal', {'amount': amount})

  async def transfer(self, account_id: str, destination_account_id: str, amount: str) -> dict:
    return await self.request('POST', f'/account/{account_id}/transfer', {'destination_account_id': destination_account_id, 'amount': amount})

  async def balance(self, account_id: str) -> dict:
    return await self.request('GET', f'/account/{account_id}/balance')

  async def reverse(self, transaction_id: str) -> dict:
    return await self.request('POST', f'/account/transaction/{transaction_id}/reversal')
