"""Frozen public top-level interface declarations for generated testbenches."""

AXIL_IN = {
    "awaddr": 16, "awprot": 3, "awvalid": 1, "wdata": 32, "wstrb": 4,
    "wvalid": 1, "bready": 1, "araddr": 16, "arprot": 3, "arvalid": 1, "rready": 1,
}
AXIL_OUT = {"awready": 1, "wready": 1, "bresp": 2, "bvalid": 1, "arready": 1,
            "rdata": 32, "rresp": 2, "rvalid": 1}
AXI_OUT = {"wdata": 128, "wstrb": 16, "wlast": 1, "wvalid": 1, "bready": 1, "rready": 1}
AXI_IN = {"wready": 1, "bid": 4, "bresp": 2, "bvalid": 1, "rid": 4,
          "rdata": 128, "rresp": 2, "rlast": 1, "rvalid": 1}
for channel in ("aw", "ar"):
    for suffix, width in {"addr": 32, "id": 4, "len": 8, "size": 3, "burst": 2,
                          "lock": 1, "cache": 4, "prot": 3, "qos": 4, "region": 4,
                          "valid": 1}.items():
        AXI_OUT[channel + suffix] = width
    AXI_IN[channel + "ready"] = 1


def declarations():
    lines = ["wire irq;"]
    for prefix, fields, kind, array in [
        ("s_axil_", AXIL_IN, "reg", False), ("s_axil_", AXIL_OUT, "wire", False),
        ("m_axi_", AXI_IN, "reg", True), ("m_axi_", AXI_OUT, "wire", True),
    ]:
        for field, width in fields.items():
            shape = ("[3:0]" if array else "") + (f"[{width-1}:0]" if width > 1 else "")
            lines.append(f"{kind} {shape} {prefix}{field}" + ("=0;" if kind == "reg" else ";"))
    return "\n".join(lines)


def reset_expression():
    return "{irq," + ",".join(["s_axil_" + p for p in AXIL_OUT] +
                              ["m_axi_" + p for p in AXI_OUT]) + "}"


def crossbar_declarations():
    lines = []
    for prefix, fields, kind in [
        ("s_axi_", AXI_OUT, "reg"), ("s_axi_", AXI_IN, "wire"),
        ("m_axi_", AXI_IN, "reg"), ("m_axi_", AXI_OUT, "wire"),
    ]:
        for field, width in fields.items():
            if prefix == "s_axi_" and field in ("awid", "arid", "bid", "rid"):
                width = 2
            shape = "[3:0]" + (f"[{width-1}:0]" if width > 1 else "")
            annotation = " /* verilator public_flat_rw */" if kind == "reg" else ""
            lines.append(f"{kind} {shape} {prefix}{field}" + annotation + ("=0;" if kind == "reg" else ";"))
    return "\n".join(lines)


def crossbar_reset_expression():
    return "{" + ",".join(["s_axi_" + p for p in AXI_IN] +
                          ["m_axi_" + p for p in AXI_OUT]) + "}"
