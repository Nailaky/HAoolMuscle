"""Composant ESPHome cm1_bridge : pont série arbitré entre la logique embarquée,
le moteur Cool Muscle CM1 et des clients TCP (application Cool Muscle Studio).

Voir docs/protocole-tcp.md pour le protocole.
"""

import ipaddress

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome import automation
from esphome.components import uart
from esphome.const import CONF_ID, CONF_PORT, CONF_TRIGGER_ID

CODEOWNERS = ["@Nailaky"]
DEPENDENCIES = ["uart", "network"]
AUTO_LOAD = ["socket"]
MULTI_CONF = True

CONF_CM1_BRIDGE_ID = "cm1_bridge_id"
CONF_ON_LINE = "on_line"
CONF_MAX_CLIENTS = "max_clients"
CONF_MIN_SPACING = "min_spacing"
CONF_MAINTENANCE_TIMEOUT = "maintenance_timeout"
CONF_ALLOWED_IPS = "allowed_ips"
CONF_MAX_LINE_LENGTH = "max_line_length"

cm1_bridge_ns = cg.esphome_ns.namespace("cm1_bridge")
CM1Bridge = cm1_bridge_ns.class_("CM1Bridge", cg.Component, uart.UARTDevice)
LineTrigger = cm1_bridge_ns.class_("LineTrigger", automation.Trigger.template(cg.std_string))


def _validate_network(value):
    value = cv.string(value)
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise cv.Invalid(f"adresse ou réseau IPv4 invalide : {value}") from exc
    if ":" in value:
        raise cv.Invalid("seul IPv4 est accepté dans allowed_ips")
    return value


CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(CM1Bridge),
            cv.Optional(CONF_PORT, default=6638): cv.port,
            cv.Optional(CONF_MAX_CLIENTS, default=4): cv.int_range(min=1, max=8),
            cv.Optional(CONF_MIN_SPACING, default="3ms"): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_MAINTENANCE_TIMEOUT, default="60s"): cv.positive_time_period_seconds,
            cv.Optional(CONF_MAX_LINE_LENGTH, default=120): cv.int_range(min=40, max=512),
            cv.Optional(CONF_ALLOWED_IPS): cv.ensure_list(_validate_network),
            cv.Optional(CONF_ON_LINE): automation.validate_automation(
                {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(LineTrigger)}
            ),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
    .extend(uart.UART_DEVICE_SCHEMA)
)

FINAL_VALIDATE_SCHEMA = uart.final_validate_device_schema("cm1_bridge", require_tx=True, require_rx=True)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await uart.register_uart_device(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_max_clients(config[CONF_MAX_CLIENTS]))
    cg.add(var.set_min_spacing(config[CONF_MIN_SPACING].total_milliseconds))
    cg.add(var.set_maintenance_timeout(config[CONF_MAINTENANCE_TIMEOUT].total_seconds))
    cg.add(var.set_max_line_length(config[CONF_MAX_LINE_LENGTH]))
    for net in config.get(CONF_ALLOWED_IPS, []):
        n = ipaddress.ip_network(net, strict=False)
        cg.add(var.add_allowed_network(int(n.network_address), int(n.netmask)))
    for conf in config.get(CONF_ON_LINE, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], var)
        await automation.build_automation(trigger, [(cg.std_string, "x")], conf)
