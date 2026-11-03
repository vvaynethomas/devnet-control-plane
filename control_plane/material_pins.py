"""Independently verified private producer release identities."""

CORE_VERSION = "0.1.1rc2"
CORE_COMMIT = "31d0661fae0a89f80290d8e645a6872431cd6dd6"
CORE_URL = "https://github.com/vvaynethomas/material-core"
CORE_WHEEL_SHA256 = "c127e5529e2611da463dca683d0dd189e3fdcf7da6908427873fc7baf4a5dc47"
UTILITY_VERSION = "0.1.0rc2"
UTILITY_COMMIT = "4e2a06146944b438f10525ef45c44cc101b417b5"
UTILITY_URL = "https://github.com/vvaynethomas/utility-chest"
UTILITY_SUBDIRECTORY = "utilities/credential-patterns"
UTILITY_WHEEL_SHA256 = "56ec8356007403ddf23a36bf17b06c0319dfb196fb0fd045995524d68a49e119"
UTILITY_REQUIREMENT = (
    f"utility-chest-credential-patterns @ git+{UTILITY_URL}.git@{UTILITY_COMMIT}"
    f"#subdirectory={UTILITY_SUBDIRECTORY}"
)
HUB_VERSION = "0.1.2"
HUB_COMMIT = "381644edec4c948375bc6f24b695bbba7b699e7a"
HUB_WHEEL_SHA256 = "537dd2fc8f792742d64fd6377b3fa706af8fb2d8f2af7b491dbe5a82a30237c1"
HUB_URL = "https://github.com/vvaynethomas/conversation-hub"
