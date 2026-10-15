"""Fix the _auth_guard_new backslash escaping AND add Jupiter endpoints to public dashboard."""
import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
with open(path, 'r') as f:
    content = f.read()

# Step 1: Fix \\\\n (4 backslashes + n) -> \\n (2 backslashes + n) on the auth_guard_new lines
content = content.replace('\\\\\\\\n', '\\\\n')

# Step 2: Add Jupiter endpoints to public_dashboard_gets in the compressed source
# The compressed source uses actual newlines. The marker uses \n (actual newline).
# We need to add this as a Python string replacement in app.py source code.
# In the app.py source, we write '\n' to represent actual newlines.
new_block = (
    '\n'
    '# Add Jupiter read-only endpoints to the public dashboard allowlist.\n'
    '# The compressed source already has public_dashboard_gets from f24d8a3;\n'
    '# extend it so the Phantom-connected wallet balance can be queried without Basic Auth.\n'
    '_jup_allow_old = \'"/api/meme/trader",\\n        }\'\n'
    '_jup_allow_new = \'"/api/meme/trader",\\n            "/api/jupiter/balance", "/api/jupiter/status",\\n        }\'\n'
    'if _jup_allow_old in _src:\n'
    '    _src = _src.replace(_jup_allow_old, _jup_allow_new, 1)\n'
)

# Insert after the auth guard RuntimeError block, before "# Strip the"
marker = 'raise RuntimeError("Could not apply read-only dashboard auth fix: source guard not found.")'
if marker in content:
    content = content.replace(marker, marker + new_block, 1)
    print('Jupiter allowlist addition inserted after auth guard block')
else:
    print('WARNING: auth guard marker not found')

with open(path, 'w') as f:
    f.write(content)

print('File written successfully')
