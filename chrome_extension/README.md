# Bob Browser Agent Chrome Extension

The Bob Browser Agent is a local Chrome side panel extension for Bob V2. It lets Bob control the active Chrome tab when a task needs a real browser session, such as logged-in pages, JavaScript-heavy sites, scrolling, clicking, typing, form filling, page text extraction, HTML extraction, and screenshots.

The extension connects to Bob over a local WebSocket at `ws://localhost:9876`. Bob starts that bridge automatically when a Bob session starts.

## Requirements

- Google Chrome or a Chromium-based browser that supports Manifest V3 side panels.
- Bob V2 installed and running locally.
- This repository checked out on your machine.

## Install In Chrome

1. Open Chrome.
2. Go to `chrome://extensions`.
3. Turn on `Developer mode`.
4. Click `Load unpacked`.
5. Select this folder: `chrome_extension/`.
6. Pin or open `bob Browser Agent` from the Chrome toolbar.

The side panel should show `Connecting` until Bob is running. Once Bob starts and the bridge is available, the panel should switch to `Connected`.

## Use With Bob

Start Bob in a terminal:

```powershell
cd bobV2
py -3.11 -m bob
```

Then ask Bob to use the browser when it actually needs your active Chrome session:

```text
open the current page and summarize what is visible
navigate to https://example.com and tell me what the page says
click the login button on the active tab
fill this form field with test data
take a screenshot of the current page
```

Bob will send browser commands to the extension. The extension executes those commands in the active tab and sends the result back to Bob.

## What It Can Do

- Navigate the active tab.
- Read visible page text.
- Read page HTML.
- Find elements by CSS selector.
- Click elements.
- Fill form fields.
- Type text into focused inputs and rich text editors.
- Scroll pages and common single-page app containers.
- Get the current URL.
- Capture screenshots.

## How It Works

1. Bob starts `bobV2/bob/bridge/chrome_bridge.py`.
2. The bridge listens locally on `127.0.0.1:9876`.
3. The Chrome extension side panel connects to `ws://localhost:9876`.
4. Bob sends JSON commands such as `navigate`, `get_page_text`, `click`, or `screenshot`.
5. The extension runs the command against the active Chrome tab.
6. The extension returns either a result or an error to Bob.

The side panel also shows a small activity log so you can see what Bob is asking Chrome to do.

## Permissions

The extension requests:

- `sidePanel`: to show the Bob side panel.
- `storage`: to support extension-side state.
- `tabs`: to find and update the active tab.
- `scripting`: to read page text, inspect HTML, click elements, and fill fields.
- `debugger`: to support reliable typing flows for editors that ignore synthetic JavaScript events.
- `<all_urls>` host access: to allow Bob to work on the active site you ask it to use.

Only install this extension from a local checkout you trust. It is designed for local development with Bob V2.

## Troubleshooting

If the panel stays disconnected:

- Make sure Bob is running in a terminal.
- Make sure only one Bob session is trying to use port `9876`.
- Reload the extension from `chrome://extensions`.
- Close and reopen the side panel.
- Restart Bob.

If a command fails:

- Make sure the active tab is a normal website, not `chrome://`, `about:`, or another restricted browser page.
- Some sites block JavaScript execution through Content Security Policy. Bob should prefer page text, HTML, find, click, scroll, or type actions before raw JavaScript.
- For logged-in pages, make sure you are already logged in inside Chrome.

## Safety Notes

Bob can click, type, navigate, read page content, and overwrite the clipboard during some typing flows. Watch the browser while Bob is working and do not ask it to interact with sensitive pages unless you understand the risk.

This extension is part of the Bob V2 prototype. It is not production software and is not an official IBM product.
