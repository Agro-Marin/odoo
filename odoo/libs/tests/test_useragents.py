import pytest

from odoo.libs._vendor.useragents import UserAgent

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36"
)
CHROMEOS = (
    "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Edg/126.0"
)
WINDOWS_PHONE = (
    "Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; Microsoft; Lumia 950) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0 Mobile Safari/537.36 "
    "Edge/15.15063"
)
OUTLOOK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Microsoft Outlook 16.0) "
    "AppleWebKit/537.36 (KHTML, like Gecko)"
)
KAIOS = (
    "Mozilla/5.0 (Mobile; LYF/F300B;Android; rv:48.0) Gecko/48.0 Firefox/48.0 KAIOS/2.5"
)
BB10 = (
    "Mozilla/5.0 (BB10; Touch) AppleWebKit/537.10+ (KHTML, like Gecko) "
    "Version/10.0.9.2372 Mobile Safari/537.10+"
)
MACOS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)
LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

EDGE_ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36 EdgA/126.0"
)
EDGE_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 EdgiOS/126.0 Mobile/15E148 Safari/605.1.15"
)
OPERA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 OPR/112.0"
)
SAMSUNG = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0 Mobile Safari/537.36"
)
FIREFOX_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) FxiOS/128.0 Mobile/15E148 Safari/605.1.15"
)


@pytest.mark.parametrize(
    ("user_agent", "platform"),
    [
        (IPHONE, "iphone"),
        (IPAD, "ipad"),
        ("Odoo/17.0 (iOS 17.5; iPhone15,2)", "iphone"),
        (ANDROID, "android"),
        (CHROMEOS, "chromeos"),
        (EDGE, "windows"),
        (WINDOWS_PHONE, "windows phone"),
        (OUTLOOK, "windows"),
        (KAIOS, "android"),
        (BB10, "blackberry"),
        (MACOS, "macos"),
        (LINUX, "linux"),
        ("curl/8.5.0", None),
    ],
)
def test_platform(user_agent, platform):
    assert UserAgent(user_agent).platform == platform


@pytest.mark.parametrize(
    ("user_agent", "browser", "version"),
    [
        (EDGE, "edge", "126.0"),
        (EDGE_ANDROID, "edge", "126.0"),
        (EDGE_IOS, "edge", "126.0"),
        (WINDOWS_PHONE, "edge", "15.15063"),
        (OPERA, "opera", "112.0"),
        (SAMSUNG, "samsung", "25.0"),
        (FIREFOX_IOS, "firefox", "128.0"),
        (ANDROID, "chrome", "126.0"),
        (IPHONE, "safari", "17.5"),
        (LINUX, "firefox", "128.0"),
    ],
)
def test_browser(user_agent, browser, version):
    parsed = UserAgent(user_agent)
    assert (parsed.browser, parsed.version) == (browser, version)
