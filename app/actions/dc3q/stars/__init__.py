"""DC3Q account-star actions, loaded from ordered Vietnamese filenames."""
from importlib import import_module

_login = import_module("app.actions.dc3q.stars.01-0_dang-nhap")
_logout = import_module("app.actions.dc3q.stars.01-2_dang-xuat")
_home = import_module("app.actions.dc3q.stars.01-4_home")

AccountLoginAction = _login.AccountLoginAction
LoginCoordinates = _login.LoginCoordinates
classify_login_ui = _login.classify_login_ui
AccountLogoutAction = _logout.AccountLogoutAction
LogoutTemplates = _logout.LogoutTemplates
reflected_point = _logout.reflected_point
select_logout_state = _logout.select_logout_state
HomeAction = _home.HomeAction

__all__ = [
    "AccountLoginAction", "LoginCoordinates", "classify_login_ui",
    "AccountLogoutAction", "LogoutTemplates", "reflected_point",
    "select_logout_state", "HomeAction",
]
