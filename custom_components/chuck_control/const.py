"""Constants for the Chuck Charger Control integration."""

DOMAIN = "chuck_control"
PHASE_ORDER_DICT = {
    "conf_1": "1/2/3",
    "conf_2": "1/3/2",
    "conf_3": "2/1/3",
    "conf_4": "2/3/1",
    "conf_5": "3/1/2",
    "conf_6": "3/2/1",
}
PHASE_ORDER_DICT_DEFAULT_CFG = "conf_1"
PHASE_ORDER = {
    "conf_1": [1, 2, 3],
    "conf_2": [1, 3, 2],
    "conf_3": [2, 1, 3],
    "conf_4": [2, 3, 1],
    "conf_5": [3, 1, 2],
    "conf_6": [3, 2, 1],
}
CONF_HAVE_NET_CURRENT_SENSOR = "have_net_current_sensor"
CONF_DEFAULT_API_BASE_URL = "http://localhost"
CONF_DEFAULT_API_USER = "admin"
CONF_DEFAULT_API_PWD = "admin"
