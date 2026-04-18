from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional


REDIRECT_PORT = 7890
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class McpOAuthFlow:
    """PKCE OAuth 2.0 authorization code flow for MCP server authentication.

    Opens a browser window for the user to authorize the connection, then
    listens on localhost for the callback and exchanges the code for a token.
    """

    def __init__(
        self,
        server_name: str,
        auth_server_url: str,
        client_id: str,
        scope: str = "",
    ) -> None:
        self.server_name = server_name
        self.auth_server_url = auth_server_url.rstrip("/")
        self.client_id = client_id
        self.scope = scope

    async def run_flow(self) -> str:
        """Complete the PKCE auth flow. Returns the access token."""
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        if self.scope:
            params["scope"] = self.scope

        auth_url = f"{self.auth_server_url}/authorize?{urllib.parse.urlencode(params)}"
        webbrowser.open(auth_url)

        code = await self._wait_for_callback(state)
        if not code:
            raise RuntimeError("OAuth callback timed out or was cancelled")

        token = await self._exchange_code(code, verifier)
        return token

    async def _wait_for_callback(self, state: str, timeout: float = 120.0) -> Optional[str]:
        """Start a local HTTP server and wait for the OAuth callback."""
        code_future: asyncio.Future[Optional[str]] = asyncio.get_running_loop().create_future()

        class _CallbackHandler:
            def __init__(self) -> None:
                self.code: Optional[str] = None

        async def handle_request(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=5)
                request_line = data.decode("utf-8", errors="replace").split("\r\n")[0]
                path = request_line.split(" ")[1] if " " in request_line else "/"
                qs = urllib.parse.urlparse(path).query
                params = urllib.parse.parse_qs(qs)
                returned_code = (params.get("code") or [""])[0]
                returned_state = (params.get("state") or [""])[0]

                if returned_state == state and returned_code:
                    body = b"<html><body><h2>Authorization successful - you can close this tab.</h2></body></html>"
                    response = (
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                    )
                    if not code_future.done():
                        code_future.set_result(returned_code)
                else:
                    body = b"<html><body><h2>Authorization failed.</h2></body></html>"
                    response = (
                        b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n"
                        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                    )
                    if not code_future.done():
                        code_future.set_result(None)

                writer.write(response)
                await writer.drain()
            except Exception:
                if not code_future.done():
                    code_future.set_result(None)
            finally:
                writer.close()

        server = await asyncio.start_server(handle_request, "localhost", REDIRECT_PORT)
        try:
            return await asyncio.wait_for(code_future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            server.close()
            await server.wait_closed()

    async def _exchange_code(self, code: str, verifier: str) -> str:
        """Exchange the authorization code for an access token."""
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": self.client_id,
            "code_verifier": verifier,
        }).encode()

        req = urllib.request.Request(
            f"{self.auth_server_url}/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        loop = asyncio.get_running_loop()
        response_bytes = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(req, timeout=15).read(),
        )
        token_data = json.loads(response_bytes.decode())
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise RuntimeError(f"No access_token in response: {token_data}")
        return access_token
