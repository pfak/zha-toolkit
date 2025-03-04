from __future__ import annotations

import json
import logging
import os
from enum import Enum

from homeassistant.util.json import save_json
from zigpy import types as t
from zigpy.zcl import foundation as f

from .params import INTERNAL_PARAMS as p
from .params import USER_PARAMS as P

LOGGER = logging.getLogger(__name__)

VERSION_TIME: float
VERSION: str
MANIFEST: dict[str, str | list[str]]


def getVersion() -> str:
    # Set name with regards to local path
    global VERSION_TIME
    global VERSION
    global MANIFEST

    fname = os.path.dirname(__file__) + "/manifest.json"

    ftime: float = 0
    try:
        VERSION_TIME
    except NameError:
        VERSION_TIME = 0
        VERSION = "Unknown"
        MANIFEST = {}

    try:
        ftime = os.path.getmtime(fname)
        if ftime != ftime:
            VERSION = "Unknown"
            MANIFEST = {}
    except Exception:
        MANIFEST = {}

    if (VERSION is None and ftime != 0) or (ftime != VERSION_TIME):
        # No version, or file change -> get version again
        LOGGER.debug(f"Read version from {fname} {ftime}<>{VERSION_TIME}")

        with open(fname) as f:
            VERSION_TIME = ftime
            MANIFEST = json.load(f)

        if MANIFEST is not None:
            if "version" in MANIFEST.keys():
                v = MANIFEST["version"]
                VERSION = v if isinstance(v, str) else "Invalid manifest"
                if VERSION == "0.0.0":
                    VERSION = "dev"

    return VERSION


# Convert string to int if possible or return original string
#  (Returning the original string is useful for named attributes)
def str2int(s):
    if not type(s) == str:
        return s
    elif s.lower() == "false":
        return 0
    elif s.lower() == "true":
        return 1
    elif s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    elif s.startswith("0") and s.isnumeric():
        return int(s, 8)
    elif s.startswith("b") and s[1:].isnumeric():
        return int(s[1:], 2)
    elif s.isnumeric():
        return int(s)
    else:
        return s


# Convert string to best boolean representation
def str2bool(s):
    if s is None or s == "":
        return False
    if s is True or s is False:
        return s
    return str2int(s) != 0


class RadioType(Enum):
    UNKNOWN = 0
    ZNP = 1
    EZSP = 2
    BELLOWS = 2


def isJsonable(x):
    try:
        json.dumps(x)
        return True
    except (TypeError, OverflowError):
        return False


def get_radiotype(app):
    if hasattr(app, "_znp"):
        return RadioType.ZNP
    if hasattr(app, "_ezsp"):
        return RadioType.EZSP
    LOGGER.debug("Type recognition for '%s' not implemented", type(app))
    return RadioType.UNKNOWN


def get_radio(app):
    if hasattr(app, "_znp"):
        return app._znp
    if hasattr(app, "_ezsp"):
        return app._ezsp
    LOGGER.debug("Type recognition for '%s' not implemented", type(app))
    return RadioType.UNKNOWN


def get_radio_version(app):
    if hasattr(app, "_znp"):
        import zigpy_znp

        return zigpy_znp.__version__
    if hasattr(app, "_ezsp"):
        import bellows

        return bellows.__version__
    LOGGER.debug("Type recognition for '%s' not implemented", type(app))
    return None


# Get zigbee IEEE address (EUI64) for the reference.
#  Reference can be entity, device, or IEEE address
async def get_ieee(app, listener, ref):
    # LOGGER.debug("Type IEEE: %s", type(ref))
    if type(ref) == str:
        # Check if valid ref address
        if ref.count(":") == 7:
            return t.EUI64.convert(ref)

        # Check if network address
        nwk = str2int(ref)
        if (type(nwk) == int) and nwk >= 0x0000 and nwk <= 0xFFF7:
            device = app.get_device(nwk=nwk)
            if device is None:
                return None
            else:
                LOGGER.debug("NWK addr 0x04x -> %s", nwk, device.ieee)
                return device.ieee

        # Todo: check if NWK address
        entity_registry = (
            await listener._hass.helpers.entity_registry.async_get_registry()
        )
        # LOGGER.debug("registry %s",entity_registry)
        registry_entity = entity_registry.async_get(ref)
        LOGGER.debug("registry_entity %s", registry_entity)
        if registry_entity is None:
            return None
        if registry_entity.platform != "zha":
            LOGGER.error("Not a ZHA device : '%s'", ref)
            return None

        device_registry = (
            await listener._hass.helpers.device_registry.async_get_registry()
        )
        registry_device = device_registry.async_get(registry_entity.device_id)
        LOGGER.debug("registry_device %s", registry_device)
        for identifier in registry_device.identifiers:
            if identifier[0] == "zha":
                return t.EUI64.convert(identifier[1])
        return None

    # Other type, suppose it's already an EUI64
    return ref


# Get a zigbee device instance for the reference.
#  Reference can be entity, device, or IEEE address
async def get_device(app, listener, reference):
    # Method is called get
    ieee = await get_ieee(app, listener, reference)
    LOGGER.debug("IEEE for get_device: %s", ieee)
    return app.get_device(ieee)


# Save state to db
def set_state(
    hass, entity_id, value, key=None, allow_create=False, force_update=False
):
    stateObj = hass.states.get(entity_id)
    if stateObj is None and allow_create is not True:
        LOGGER.warning("Entity_id '%s' not found", entity_id)
        return

    if stateObj is not None:
        # Copy existing attributes, to update selected item
        stateAttrs = stateObj.attributes.copy()
    else:
        stateAttrs = {}

    # LOGGER.debug("Before: entity:%s key:%s value:%s attrs:%s",
    #              entity_id, key, value, stateAttrs)
    if key is not None:
        stateAttrs[key] = value
        value = None

    # LOGGER.debug("entity:%s key:%s value:%s attrs:%s",
    #              entity_id, key, value, stateAttrs)

    # Store to DB_state
    hass.states.async_set(
        entity_id=entity_id,
        new_state=value,
        attributes=stateAttrs,
        force_update=force_update,
        context=None,
    )


# Find endpoint matching in_cluster
def find_endpoint(dev, cluster_id):
    cnt = 0
    endpoint_id = None

    for key, value in dev.endpoints.items():
        if key == 0:
            continue
        if cluster_id in value.in_clusters:
            endpoint_id = key
            cnt = cnt + 1

    if cnt == 0:
        for key, value in dev.endpoints.items():
            if key == 0:
                continue
            if cluster_id in value.in_clusters:
                endpoint_id = key
                cnt = cnt + 1

        if cnt == 0:
            LOGGER.error("No Endpoint found for cluster '%s'", cluster_id)
        else:
            LOGGER.error(
                "No Endpoint found for in_cluster, found out_cluster '%s'",
                cluster_id,
            )

    if cnt > 1:
        endpoint_id = None
        LOGGER.error(
            "More than one Endpoint found for cluster '%s'", cluster_id
        )
    if cnt == 1:
        LOGGER.debug(
            "Endpoint %s found for cluster '%s'", endpoint_id, cluster_id
        )

    return endpoint_id


def get_cluster_from_params(
    dev, params: dict[str, int | str | list[int | str]], event_data: dict
):
    """
    Get in or outcluster (and endpoint) with best
    correspondence to values provided in params
    """

    # Get best endpoint
    if params[p.EP_ID] is None or params[p.EP_ID] == "":
        params[p.EP_ID] = find_endpoint(dev, params[p.CLUSTER_ID])

    if params[p.EP_ID] not in dev.endpoints:
        msg = f"Endpoint {params[p.EP_ID]} not found for '{dev.ieee!r}"
        LOGGER.error(msg)
        raise Exception(msg)

    cluster_id = params[p.CLUSTER_ID]
    if not isinstance(cluster_id, int):
        msg = f"Cluster must be numeric {cluster_id}"
        raise Exception(msg)

    cluster = None
    if cluster_id not in dev.endpoints[params[p.EP_ID]].in_clusters:
        msg = "InCluster 0x{:04X} not found for '{}', endpoint {}".format(
            cluster_id, repr(dev.ieee), params[p.EP_ID]
        )
        if cluster_id in dev.enddev.points[params[p.EP_ID]].out_clusters:
            msg = f'"Using" OutCluster. {msg}'
            LOGGER.warning(msg)
            if "warnings" not in event_data:
                event_data["warnings"] = []
            event_data["warnings"].append(msg)
            cluster = dev.endpoints[params[p.EP_ID]].out_clusters[cluster_id]
        else:
            LOGGER.error(msg)
            raise Exception(msg)
    else:
        cluster = dev.endpoints[params[p.EP_ID]].in_clusters[cluster_id]

    return cluster


def write_json_to_file(data, subdir, fname, desc, listener=None):
    if listener is None or subdir == "local":
        base_dir = os.path.dirname(__file__)
    else:
        base_dir = listener._hass.config.config_dir

    out_dir = os.path.join(base_dir, subdir)
    if not os.path.isdir(out_dir):
        os.mkdir(out_dir)

    file_name = os.path.join(out_dir, fname)
    save_json(file_name, data)
    LOGGER.debug(f"Finished writing {desc} in '{file_name}'")


def append_to_csvfile(
    fields, subdir, fname, desc, listener=None, overwrite=False
):
    if listener is None or subdir == "local":
        base_dir = os.path.dirname(__file__)
    else:
        base_dir = listener._hass.config.config_dir

    out_dir = os.path.join(base_dir, subdir)
    if not os.path.isdir(out_dir):
        os.mkdir(out_dir)

    file_name = os.path.join(out_dir, fname)

    import csv

    with open(file_name, "w" if overwrite else "a") as f:
        writer = csv.writer(f)
        writer.writerow(fields)

    if overwrite:
        LOGGER.debug(f"Wrote {desc} to '{file_name}'")
    else:
        LOGGER.debug(f"Appended {desc} to '{file_name}'")


def get_attr_id(cluster, attribute):
    # Try to get attribute id from cluster
    try:
        if isinstance(attribute, str):
            return cluster.attributes_by_name(attribute)
    except Exception:
        return None

    # By default, just try to convert it to an int
    return str2int(attribute)


def get_attr_type(cluster, attr_id):
    """Get type for attribute in cluster, or None if not found"""
    try:
        return f.DATA_TYPES.pytype_to_datatype_id(
            cluster.attributes.get(attr_id, (None, f.Unknown))[1]
        )
    except Exception:  # nosec
        pass

    return None


def attr_encode(attr_val_in, attr_type):  # noqa C901
    # Convert attribute value (provided as a string)
    # to appropriate attribute value.
    # If the attr_type is not set, only read the attribute.
    attr_obj = None
    if attr_type == 0x10:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.Bool(compare_val))
    elif attr_type == 0x20:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint8_t(compare_val))
    elif attr_type == 0x21:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint16_t(compare_val))
    elif attr_type == 0x22:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint24_t(compare_val))
    elif attr_type == 0x23:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint32_t(compare_val))
    elif attr_type == 0x24:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint32_t(compare_val))
    elif attr_type == 0x25:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint48_t(compare_val))
    elif attr_type == 0x26:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint56_t(compare_val))
    elif attr_type == 0x27:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.uint64_t(compare_val))
    elif attr_type == 0x28:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int8s(compare_val))
    elif attr_type == 0x29:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int16s(compare_val))
    elif attr_type == 0x2A:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int24s(compare_val))
    elif attr_type == 0x2B:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int32s(compare_val))
    elif attr_type == 0x2C:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int32s(compare_val))
    elif attr_type == 0x2D:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int48s(compare_val))
    elif attr_type == 0x2E:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int56s(compare_val))
    elif attr_type == 0x2F:
        compare_val = str2int(attr_val_in)
        attr_obj = f.TypeValue(attr_type, t.int64s(compare_val))
    elif attr_type in [0x41, 0x42]:  # Octet string
        # Octet string requires length -> LVBytes
        compare_val = t.LVBytes(attr_val_in)

        if type(attr_val_in) == str:
            attr_val_in = bytes(attr_val_in, "utf-8")

        if isinstance(attr_val_in, list):
            # Convert list to List of uint8_t
            attr_val_in = t.List[t.uint8_t](
                [t.uint8_t(i) for i in attr_val_in]
            )

        attr_obj = f.TypeValue(attr_type, t.LVBytes(attr_val_in))
    elif attr_type == 0xFF or attr_type is None:
        compare_val = str2int(attr_val_in)
        # This should not happen ideally
        attr_obj = f.TypeValue(attr_type, t.LVBytes(compare_val))
    else:
        # Try to apply conversion using foundation DATA_TYPES table
        data_type = f.DATA_TYPES[attr_type][1]
        LOGGER.debug(f"Data type '{data_type}' for attr type {attr_type}")
        compare_val = data_type(str2int(attr_val_in))
        attr_obj = f.TypeValue(attr_type, data_type(compare_val))
        LOGGER.debug(
            "Converted %s to %s - will compare to %s - Type: 0x%02X",
            attr_val_in,
            attr_obj,
            compare_val,
            attr_type,
        )

    if attr_obj is None:
        msg = (
            "attr_type {} not supported, "
            "or incorrect parameters (attr_val={})"
        ).format(attr_type, attr_val_in)
        LOGGER.error(msg)
    else:
        msg = None

    return attr_obj, msg, compare_val


# Common method to extract and convert parameters.
#
# Most parameters are similar, this avoids repeating
# code.
#
def extractParams(  # noqa: C901
    service,
) -> dict[str, None | int | str | list[int | str] | bytes]:
    rawParams = service.data

    LOGGER.debug("Parameters '%s'", rawParams)

    # Potential parameters, initialized to None
    # TODO: Not all parameters are decoded in this function yet
    params: dict[str, None | int | str | list[int | str] | bytes] = {
        p.CMD_ID: None,
        p.EP_ID: None,
        p.CLUSTER_ID: None,
        p.ATTR_ID: None,
        p.ATTR_TYPE: None,
        p.ATTR_VAL: None,
        p.CODE: None,  # Install code (join with code)
        p.MIN_INTERVAL: None,
        p.MAX_INTERVAL: None,
        p.REPORTABLE_CHANGE: None,
        p.DIR: 0,
        p.MANF: None,
        p.TRIES: 1,
        p.EXPECT_REPLY: True,
        p.ARGS: [],
        p.STATE_ID: None,
        p.STATE_ATTR: None,
        p.ALLOW_CREATE: False,
        p.EVT_SUCCESS: None,
        p.EVT_FAIL: None,
        p.EVT_DONE: None,
        p.FAIL_EXCEPTION: False,
        p.READ_BEFORE_WRITE: True,
        p.READ_AFTER_WRITE: True,
        p.WRITE_IF_EQUAL: False,
        p.CSV_FILE: None,
        p.CSV_LABEL: None,
    }

    # Endpoint to send command to
    if P.ENDPOINT in rawParams:
        params[p.EP_ID] = str2int(rawParams[P.ENDPOINT])

    # Cluster to send command to
    if P.CLUSTER in rawParams:
        params[p.CLUSTER_ID] = str2int(rawParams[P.CLUSTER])

    # Attribute to send command to
    if P.ATTRIBUTE in rawParams:
        params[p.ATTR_ID] = str2int(rawParams[P.ATTRIBUTE])

    # Attribute to send command to
    if P.ATTR_TYPE in rawParams:
        params[p.ATTR_TYPE] = str2int(rawParams[P.ATTR_TYPE])

    # Attribute to send command to
    if P.ATTR_VAL in rawParams:
        params[p.ATTR_VAL] = str2int(rawParams[P.ATTR_VAL])

    # Install code
    if P.CODE in rawParams:
        params[p.CODE] = str2int(rawParams[P.CODE])

    # The command to send
    if P.CMD in rawParams:
        params[p.CMD_ID] = str2int(rawParams[P.CMD])

    # The direction (to in or out cluster)
    if P.DIR in rawParams:
        params[p.DIR] = str2int(rawParams[P.DIR])

    # Get manufacturer
    if P.MANF in rawParams:
        params[p.MANF] = str2int(rawParams[P.MANF])

    manf = params[p.MANF]
    if manf == "" or manf == 0:
        params[p.MANF] = b""  # Not None, force empty manf

    # Get tries
    if P.TRIES in rawParams:
        params[p.TRIES] = str2int(rawParams[P.TRIES])

    # Get expect_reply
    if P.EXPECT_REPLY in rawParams:
        params[p.EXPECT_REPLY] = str2int(rawParams[P.EXPECT_REPLY]) == 0

    if P.FAIL_EXCEPTION in rawParams:
        params[p.FAIL_EXCEPTION] = str2int(rawParams[P.FAIL_EXCEPTION]) == 0

    if P.ARGS in rawParams:
        cmd_args = []
        for val in rawParams[P.ARGS]:
            LOGGER.debug("cmd arg %s", val)
            lval = str2int(val)
            if isinstance(lval, list):
                # Convert list to List of uint8_t
                lval = t.List[t.uint8_t]([t.uint8_t(i) for i in lval])
                # Convert list to LVList structure
                # lval = t.LVList(lval)
            cmd_args.append(lval)
            LOGGER.debug("cmd converted arg %s", lval)
        params[p.ARGS] = cmd_args

    if P.MIN_INTRVL in rawParams:
        params[p.MIN_INTERVAL] = str2int(rawParams[P.MIN_INTRVL])
    if P.MAX_INTRVL in rawParams:
        params[p.MAX_INTERVAL] = str2int(rawParams[P.MAX_INTRVL])
    if P.REPTBLE_CHG in rawParams:
        params[p.REPORTABLE_CHANGE] = str2int(rawParams[P.REPTBLE_CHG])

    if P.STATE_ID in rawParams:
        params[p.STATE_ID] = rawParams[P.STATE_ID]

    if P.STATE_ATTR in rawParams:
        params[p.STATE_ATTR] = rawParams[P.STATE_ATTR]

    if P.READ_BEFORE_WRITE in rawParams:
        params[p.READ_BEFORE_WRITE] = str2bool(rawParams[P.READ_BEFORE_WRITE])

    if P.READ_AFTER_WRITE in rawParams:
        params[p.READ_AFTER_WRITE] = str2bool(rawParams[P.READ_AFTER_WRITE])

    if P.WRITE_IF_EQUAL in rawParams:
        params[p.WRITE_IF_EQUAL] = str2bool(rawParams[P.WRITE_IF_EQUAL])

    if P.STATE_ATTR in rawParams:
        params[p.STATE_ATTR] = rawParams[P.STATE_ATTR]

    if P.ALLOW_CREATE in rawParams:
        allow = str2int(rawParams[P.ALLOW_CREATE])
        params[p.ALLOW_CREATE] = (allow is not None) and (
            (allow is True) or (allow == 1)
        )

    if P.EVENT_DONE in rawParams:
        params[p.EVT_DONE] = rawParams[P.EVENT_DONE]

    if P.EVENT_FAIL in rawParams:
        params[p.EVT_FAIL] = rawParams[P.EVENT_FAIL]

    if P.EVENT_SUCCESS in rawParams:
        params[p.EVT_SUCCESS] = rawParams[P.EVENT_SUCCESS]

    if P.OUTCSV in rawParams:
        params[p.CSV_FILE] = rawParams[P.OUTCSV]

    if P.CSVLABEL in rawParams:
        params[p.CSV_LABEL] = rawParams[P.CSVLABEL]

    return params
