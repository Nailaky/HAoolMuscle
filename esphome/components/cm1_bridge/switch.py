import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import switch

from . import CM1Bridge, CONF_CM1_BRIDGE_ID, cm1_bridge_ns

MaintenanceSwitch = cm1_bridge_ns.class_("MaintenanceSwitch", switch.Switch, cg.Component)

CONFIG_SCHEMA = (
    switch.switch_schema(MaintenanceSwitch, icon="mdi:wrench")
    .extend({cv.GenerateID(CONF_CM1_BRIDGE_ID): cv.use_id(CM1Bridge)})
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await switch.new_switch(config)
    await cg.register_component(var, config)
    parent = await cg.get_variable(config[CONF_CM1_BRIDGE_ID])
    cg.add(var.set_parent(parent))
    cg.add(parent.set_maintenance_switch(var))
