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
HUB_VERSION = "0.1.6"
HUB_COMMIT = "ea8d608b00aa1900132b2d2f33d90561143fa471"
HUB_WHEEL_SHA256 = "bb0da00debc8c13b166030b14eb26e3100afff65318ca1dd7a3b68dbc8448c16"
HUB_URL = "https://github.com/vvaynethomas/conversation-hub"
