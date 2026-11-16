"""MCP server for the banking core (../banking-core).

Exposes the core's HTTP API as MCP tools. The core enforces RBAC: every tool
acts with the permissions of the user logged in (BANKING_EMAIL), so an operator
or a client only sees and does what their role allows.

Environment variables (read from .env if it exists):
  BANKING_API_URL   core URL, http://localhost:8080 by default
  BANKING_EMAIL     user the server logs in with
  BANKING_PASSWORD  password of that user
"""
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from banking_client import BankingClient, BankingError

load_dotenv(Path(__file__).with_name('.env'))

client = BankingClient(
  base_url=os.getenv('BANKING_API_URL', 'http://localhost:8080'),
  email=os.getenv('BANKING_EMAIL'),
  password=os.getenv('BANKING_PASSWORD'),
)

mcp = FastMCP(
  name='banking-core',
  instructions=(
    'Tools for a double-entry banking core in MXN. Accounts are NOSTRO (the bank\'s own) '
    'or VOSTRO (a client\'s). Amounts are strings with at most 2 decimals, e.g. "150.00", never floats. '
    'Every operation runs with the permissions of the logged-in user; use whoami to see who that is. '
    'Use list_accounts to find account ids before operating on them. '
    'Deposits, withdrawals, transfers and reversals move real money in the ledger: confirm with the user before running them.'
  ),
)

READ_ONLY = {'readOnlyHint': True, 'idempotentHint': True, 'openWorldHint': False}
WRITE = {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': False, 'openWorldHint': False}
DESTRUCTIVE = {'readOnlyHint': False, 'destructiveHint': True, 'idempotentHint': False, 'openWorldHint': False}

Amount = Annotated[str, Field(description='Amount in MXN as text, greater than zero and with at most 2 decimals, e.g. "1500.00"', pattern=r'^\s*\d+(\.\d{1,2})?\s*$')]
Email = Annotated[str, Field(description='User email')]
Password = Annotated[str, Field(description='Password')]
Alias = Annotated[str, Field(description='Name that identifies the account, e.g. "Ahorro" or "Caja principal"')]


async def call(coroutine):
  """Turns the core's errors into ToolError so the model sees the core's message."""
  try:
    return await coroutine
  except BankingError as error:
    raise ToolError(f'[{error.status}] {error}') from error


# --- session -------------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def login(email: Email, password: Password) -> dict:
  """Logs in to the banking core as another user. The following tools act with that user's permissions."""
  data = await call(client.login(email, password))
  return {'email': email, 'role': client.claims().get('role'), 'must_change_password': data.get('must_change_password', False)}


@mcp.tool(annotations=READ_ONLY)
async def whoami() -> dict:
  """Profile of the logged-in user: id, email, name, role and whether they must change their password."""
  if client.token is None:
    await call(client.login())
  return await call(client.user_profile(client.claims()['sub']))


@mcp.tool(annotations=WRITE)
async def change_password(
  current_password: Annotated[str, Field(description='Current password')],
  new_password: Annotated[str, Field(description='New password')],
) -> dict:
  """Changes the logged-in user's password. It is the only thing allowed while must_change_password is true."""
  return await call(client.change_password(current_password, new_password))


# --- users ---------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def list_users() -> dict:
  """Lists every user (admin only), oldest to newest."""
  return await call(client.list_users())


@mcp.tool(annotations=READ_ONLY)
async def get_user(user_id: Annotated[UUID, Field(description='User id')]) -> dict:
  """Profile of a user by id."""
  return await call(client.user_profile(str(user_id)))


@mcp.tool(annotations=WRITE)
async def create_admin(email: Email, password: Annotated[str, Field(description='Initial password; the user must change it on first login')]) -> dict:
  """Creates an ADMIN user."""
  return await call(client.signup_admin(email, password))


@mcp.tool(annotations=WRITE)
async def create_operator(email: Email, password: Annotated[str, Field(description='Initial password; the user must change it on first login')]) -> dict:
  """Creates an OPERATOR user."""
  return await call(client.signup_operator(email, password))


@mcp.tool(annotations=DESTRUCTIVE)
async def deactivate_user(email: Email) -> dict:
  """Deactivates a user by email: they can no longer log in."""
  return await call(client.deactivate_user(email))


# --- accounts ------------------------------------------------------------------

@mcp.tool(annotations=READ_ONLY)
async def list_accounts() -> dict:
  """Lists the accounts with holder and current balance: every NOSTRO and VOSTRO for operator and admin, only one's own for a client."""
  return await call(client.list_accounts())


@mcp.tool(annotations=READ_ONLY)
async def get_account_movements(account_id: Annotated[UUID, Field(description='Account id')]) -> dict:
  """Movement history of an account with the balance after each movement. The current balance is the last movement's."""
  return await call(client.balance(str(account_id)))


@mcp.tool(annotations=WRITE)
async def open_client_account(
  email: Annotated[str, Field(description='Email of the new client')],
  password: Annotated[str, Field(description='Initial password; the client must change it on first login')],
  name: Annotated[str, Field(description='Full name of the client')],
  alias: Alias,
) -> dict:
  """Signs up a new CLIENT user together with their first VOSTRO account."""
  return await call(client.signup_client(email, password, name, alias))


@mcp.tool(annotations=WRITE)
async def open_vostro_account(email: Annotated[str, Field(description='Email of an existing client')], alias: Alias) -> dict:
  """Opens an additional VOSTRO account for an existing client."""
  return await call(client.open_vostro(email, alias))


@mcp.tool(annotations=WRITE)
async def open_nostro_account(alias: Alias) -> dict:
  """Opens a NOSTRO account (the bank's own)."""
  return await call(client.open_nostro(alias))


# --- operations ----------------------------------------------------------------

@mcp.tool(annotations=WRITE)
async def deposit(account_id: Annotated[UUID, Field(description='Account that receives the money')], amount: Amount) -> dict:
  """Deposits external money into an account. Returns the transaction and the new balance."""
  return await call(client.deposit(str(account_id), amount.strip()))


@mcp.tool(annotations=DESTRUCTIVE)
async def withdraw(account_id: Annotated[UUID, Field(description='Account the money leaves from')], amount: Amount) -> dict:
  """Withdraws money from an account. Fails if the balance is not enough. Returns the transaction and the new balance."""
  return await call(client.withdraw(str(account_id), amount.strip()))


@mcp.tool(annotations=DESTRUCTIVE)
async def transfer(
  account_id: Annotated[UUID, Field(description='Source account')],
  destination_account_id: Annotated[UUID, Field(description='Destination account')],
  amount: Amount,
) -> dict:
  """Transfers money between two accounts. Returns the transaction and the source account's new balance."""
  return await call(client.transfer(str(account_id), str(destination_account_id), amount.strip()))


@mcp.tool(annotations=DESTRUCTIVE)
async def reverse_transaction(transaction_id: Annotated[UUID, Field(description='Transaction to reverse')]) -> dict:
  """Fully reverses a transaction (deposit, withdrawal or transfer) with a new REVERSAL transaction. Returns the new balance of each affected account."""
  return await call(client.reverse(str(transaction_id)))


if __name__ == '__main__':
  mcp.run()
