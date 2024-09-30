#
# This file is part of LiteX.
#
# Copyright (c) 2021 Franck Jullien <franck.jullien@collshade.fr>
# SPDX-License-Identifier: BSD-2-Clause

import os
import csv
import re
import datetime

from xml.dom import expatbuilder
import xml.etree.ElementTree as et

from migen import *

from litex.build import tools

namespaces = {
    "efxpt" : "http://www.efinixinc.com/peri_design_db",
    "xi"    : "http://www.w3.org/2001/XInclude"
}

# Interface Writer Block ---------------------------------------------------------------------------

class InterfaceWriterBlock(dict):
    def generate(self):
        raise NotImplementedError # Must be overloaded

class InterfaceWriterXMLBlock(dict):
    def generate(self):
        raise NotImplementedError # Must be overloaded

# Interface Writer  --------------------------------------------------------------------------------

class InterfaceWriter:
    def __init__(self, efinity_path):
        self.efinity_path = efinity_path
        self.blocks       = []
        self.xml_blocks   = []
        self.fix_xml      = []
        self.filename     = ""
        self.platform     = None

    def set_build_params(self, platform, build_name):
        self.filename = build_name
        self.platform = platform

    def fix_xml_values(self):
        et.register_namespace("efxpt", "http://www.efinixinc.com/peri_design_db")
        tree = et.parse(self.filename + ".peri.xml")
        root = tree.getroot()
        for tag, name, values in self.fix_xml:
            for e in tree.iter():
                if (tag in e.tag) and (name == e.get("name")):
                    for n, v in values:
                        e.set(n, v)

        xml_string = et.tostring(root, "utf-8")
        reparsed = expatbuilder.parseString(xml_string, False)
        print_string = reparsed.toprettyxml(indent="    ")

        # Remove lines with only whitespaces. Not sure why they are here
        print_string = os.linesep.join([s for s in print_string.splitlines() if s.strip()])

        tools.write_to_file("{}.peri.xml".format(self.filename), print_string)

    def generate_xml_blocks(self):
        et.register_namespace("efxpt", "http://www.efinixinc.com/peri_design_db")
        tree = et.parse(self.filename + ".peri.xml")
        root = tree.getroot()

        for block in self.xml_blocks:
            if isinstance(block, InterfaceWriterXMLBlock):
                block.generate(root, namespaces)
            else:
                if block["type"] == "DRAM":
                    self.add_dram_xml(root, block)

        xml_string = et.tostring(root, "utf-8")
        reparsed = expatbuilder.parseString(xml_string, False)
        print_string = reparsed.toprettyxml(indent="    ")

        # Remove lines with only whitespaces. Not sure why they are here
        print_string = os.linesep.join([s for s in print_string.splitlines() if s.strip()])

        tools.write_to_file("{}.peri.xml".format(self.filename), print_string)

    def header(self, build_name, partnumber):
        header = "# Autogenerated by LiteX / git: " + tools.get_litex_git_revision()
        header += """
import os
import sys
import pprint

home = "{0}"

os.environ["EFXPT_HOME"]  = home + "/pt"
os.environ["EFXPGM_HOME"] = home + "/pgm"
os.environ["EFXDBG_HOME"] = home + "/debugger"
os.environ["EFXIPM_HOME"] = home + "/ipm"

sys.path.append(home + "/pt/bin")
sys.path.append(home + "/lib/python3.8/site-packages")

from api_service.design import DesignAPI
from api_service.device import DeviceAPI

is_verbose = {1}

design = DesignAPI(is_verbose)
device = DeviceAPI(is_verbose)

design.create("{2}", "{3}", "./../gateware", overwrite=True)

"""
        return header.format(self.efinity_path, "True", build_name, partnumber)

    def iobank_info(self, iobank_info):
        cmd = "# ---------- IOBANK INFO ---------\n"
        for name, iostd in iobank_info:
            cmd += 'design.set_iobank_voltage("{0}", "{1}")\n'.format(name, iostd[:3])
        cmd += "# ---------- END IOBANK INFO ---------\n\n"
        return cmd

    def get_block(self, name):
        for b in self.blocks:
            if b["name"] == name:
                return b
        return None

    def generate_mipi_tx(self, block, verbose=True):
        name = block["name"]
        cmd = "# ---------- MIPI TX {} ---------\n".format(name)
        cmd += f'design.create_block("{name}","MIPI_TX_LANE", mode="{block["mode"]}")\n'
        for p, v in block["props"].items():
            cmd += f'design.set_property("{name}","{p}","{v}","MIPI_TX_LANE")\n'
        cmd += f'design.assign_resource("{name}","{block["ressource"]}","MIPI_TX_LANE")\n'
        cmd += "# ---------- END MIPI TX {} ---------\n\n".format(name)
        return cmd

    def generate_mipi_rx(self, block, verbose=True):
        name = block["name"]

        conn_type = ""
        if "conn_type" in block:
            conn_type = f', conn_type="{block["conn_type"]}"'

        cmd = "# ---------- MIPI RX {} ---------\n".format(name)
        cmd += f'design.create_block("{name}","MIPI_RX_LANE", mode="{block["mode"]}"' + conn_type + ')\n'
        for p, v in block["props"].items():
            cmd += f'design.set_property("{name}","{p}","{v}","MIPI_RX_LANE")\n'
        cmd += f'design.assign_resource("{name}","{block["ressource"]}","MIPI_RX_LANE")\n'
        cmd += "# ---------- END MIPI RX {} ---------\n\n".format(name)
        return cmd

    def generate_gpio(self, block, verbose=True):
        name = block["name"]
        mode = block["mode"]
        prop = block["properties"]
        cmd = ""

        if mode == "INOUT":
            if len(block["location"]) == 1:
                cmd += f'design.create_inout_gpio("{name}")\n'
                cmd += f'design.assign_pkg_pin("{name}","{block["location"][0]}")\n'
            else:
                cmd += f'design.create_inout_gpio("{name}",{block["size"]-1},0)\n'
                for i, pad in enumerate(block["location"]):
                    cmd += f'design.assign_pkg_pin("{name}[{i}]","{pad}")\n'

            if "oe_reg" in block:
                cmd += f'design.set_property("{name}","OE_REG","{block["oe_reg"]}")\n'

        if mode == "INPUT":
            if len(block["location"]) == 1:
                cmd += f'design.create_input_gpio("{name}")\n'
                cmd += f'design.assign_pkg_pin("{name}","{block["location"][0]}")\n'
            else:
                cmd += f'design.create_input_gpio("{name}",{block["size"]-1},0)\n'
                for i, pad in enumerate(block["location"]):
                    cmd += f'design.assign_pkg_pin("{name}[{i}]","{pad}")\n'
        
        if mode == "INPUT" or mode == "INOUT":
            if "in_reg" in block:
                in_clk_pin = block["in_clk_pin"]
                if isinstance(in_clk_pin, ClockSignal):
                    # Try to find cd name
                    in_clk_pin_name = self.platform.clks.get(in_clk_pin.cd, None)
                    # If not found cd name has been updated with "_clk" as suffix.
                    if in_clk_pin_name is None:
                        in_clk_pin_name = self.platform.clks.get(in_clk_pin.cd + "_clk")
                    in_clk_pin = in_clk_pin_name

                cmd += f'design.set_property("{name}","IN_REG","{block["in_reg"]}")\n'
                cmd += f'design.set_property("{name}","IN_CLK_PIN","{in_clk_pin}")\n'
                if "in_delay" in block:
                    cmd += f'design.set_property("{name}","INDELAY","{block["in_delay"]}")\n'
            if "in_clk_inv" in block:
                cmd += f'design.set_property("{name}","IS_INCLK_INVERTED","{block["in_clk_inv"]}")\n'

        if mode == "OUTPUT":
            if len(block["location"]) == 1:
                cmd += 'design.create_output_gpio("{}")\n'.format(name)
                cmd += 'design.assign_pkg_pin("{}","{}")\n'.format(name, block["location"][0])
            else:
                cmd += 'design.create_output_gpio("{}",{},0)\n'.format(name, block["size"]-1)
                for i, pad in enumerate(block["location"]):
                    cmd += 'design.assign_pkg_pin("{}[{}]","{}")\n'.format(name, i, pad)

        if mode == "OUTPUT" or mode == "INOUT":
            if "out_reg" in block:
                cmd += 'design.set_property("{}","OUT_REG","{}")\n'.format(name, block["out_reg"])
                cmd += 'design.set_property("{}","OUT_CLK_PIN","{}")\n'.format(name, block["out_clk_pin"])
                if "out_delay" in block:
                    cmd += 'design.set_property("{}","OUTDELAY","{}")\n'.format(name, block["out_delay"])

            if "out_clk_inv" in block:
                cmd += f'design.set_property("{name}","IS_OUTCLK_INVERTED","{block["out_clk_inv"]}")\n'

            if "drive_strength" in block:
                cmd += 'design.set_property("{}","DRIVE_STRENGTH","{}")\n'.format(name, block["drive_strength"])
            if "slewrate" in block:
                cmd += 'design.set_property("{}","SLEWRATE","{}")\n'.format(name, block["slewrate"])
            if "const_output" in block:
                if not isinstance(block["const_output"], list):
                    cmd += f'design.set_property("{name}","CONST_OUTPUT","{block["const_output"]}")\n'
                else:
                    for i, val in enumerate(block["const_output"]):
                        cmd += f'design.set_property("{name}[{i}]","CONST_OUTPUT","{val}")\n'

        if mode == "INOUT" or mode == "INPUT" or mode == "OUTPUT":
            if prop:
                for p, val in prop:
                    cmd += 'design.set_property("{}","{}","{}")\n'.format(name, p, val)
            cmd += "\n"
            return cmd

        if mode == "INPUT_CLK":
            cmd += 'design.create_input_clock_gpio("{}")\n'.format(name)
            cmd += 'design.set_property("{}","IN_PIN","{}")\n'.format(name, name)
            cmd += 'design.assign_pkg_pin("{}","{}")\n\n'.format(name, block["location"])
            if prop:
                for p, val in prop:
                    cmd += 'design.set_property("{}","{}","{}")\n'.format(name, p, val)
            cmd += "\n"
            return cmd

        if mode == "MIPI_CLKIN":
            cmd += 'design.create_mipi_input_clock_gpio("{}")\n'.format(name)
            cmd += 'design.assign_pkg_pin("{}","{}")\n\n'.format(name, block["location"])
            return cmd

        if mode == "OUTPUT_CLK":
            cmd += 'design.create_clockout_gpio("{}")\n'.format(name)
            cmd += 'design.set_property("{}","OUT_CLK_PIN","{}")\n'.format(name, name)
            cmd += 'design.assign_pkg_pin("{}","{}")\n\n'.format(name, block["location"])
            if "out_clk_inv" in block:
                cmd += f'design.set_property("{name}","IS_OUTCLK_INVERTED","{block["out_clk_inv"]}")\n'
            if prop:
                for p, val in prop:
                    cmd += 'design.set_property("{}","{}","{}")\n'.format(name, p, val)
            cmd += "\n"
            return cmd

        cmd = "# TODO: " + str(block) +"\n"
        return cmd

    def generate_pll(self, block, partnumber, verbose=True):
        name = block["name"]
        cmd = "# ---------- PLL {} ---------\n".format(name)
        cmd += 'design.create_block("{}", block_type="PLL")\n'.format(name)
        cmd += 'pll_config = {{ "REFCLK_FREQ":"{}" }}\n'.format(block["input_freq"] / 1e6)
        cmd += 'design.set_property("{}", pll_config, block_type="PLL")\n\n'.format(name)

        if block["input_clock"] == "LVDS_RX":
            if block["version"] == "V3":
                cmd += 'design.gen_pll_ref_clock("{}", pll_res="{}", refclk_src="EXTERNAL", refclk_name="{}", ext_refclk_no="{}", ext_refclk_type="LVDS_RX")\n\n' \
                        .format(name, block["resource"], block["input_clock_pad"], block["clock_no"])

            else:
                cmd += 'design.set_property("{}","EXT_CLK","EXT_CLK{}","PLL")\n'.format(name, block["clock_no"])
                cmd += 'design.assign_resource("{}","{}","PLL")\n'.format(name, block["resource"])


        elif block["input_clock"] == "EXTERNAL":
            # PLL V1 has a different configuration
            if partnumber[0:2] in ["T4", "T8"] and partnumber != "T8Q144":
                cmd += 'design.gen_pll_ref_clock("{}", pll_res="{}", refclk_res="{}", refclk_name="{}", ext_refclk_no="{}")\n\n' \
                    .format(name, block["resource"], block["input_clock_pad"], block["input_clock_name"], block["clock_no"])
            else:
                cmd += 'design.gen_pll_ref_clock("{}", pll_res="{}", refclk_src="{}", refclk_name="{}", ext_refclk_no="{}")\n\n' \
                    .format(name, block["resource"], block["input_clock"], block["input_clock_name"], block["clock_no"])
            for p, val in block["input_properties"]:
                cmd += 'design.set_property("{}","{}","{}")\n'.format(block["input_clock_name"], p, val)
        else:
            cmd += 'design.gen_pll_ref_clock("{}", pll_res="{}", refclk_name="{}", refclk_src="CORE")\n'.format(name, block["resource"], block["input_signal"])
            cmd += 'design.set_property("{}", "CORE_CLK_PIN", "{}", block_type="PLL")\n\n'.format(name, block["input_signal"])

        cmd += 'design.set_property("{}","LOCKED_PIN","{}", block_type="PLL")\n'.format(name, block["locked"])
        if block["rstn"] != "":
            cmd += 'design.set_property("{}","RSTN_PIN","{}", block_type="PLL")\n\n'.format(name, block["rstn"])

        if block.get("shift_ena", None) is not None:
            cmd += 'design.set_property("{}","PHASE_SHIFT_ENA_PIN","{}","PLL")\n'.format(name, block["shift_ena"].name)
            cmd += 'design.set_property("{}","PHASE_SHIFT_PIN","{}","PLL")\n'.format(name, block["shift"].name)
            cmd += 'design.set_property("{}","PHASE_SHIFT_SEL_PIN","{}","PLL")\n'.format(name, block["shift_sel"].name)

         # Output clock 0 is enabled by default
        for i, clock in enumerate(block["clk_out"]):
            if i > 0:
                cmd += 'pll_config = {{ "CLKOUT{}_EN":"1", "CLKOUT{}_PIN":"{}" }}\n'.format(i, i, clock[0])
            else:
                cmd += 'pll_config = {{ "CLKOUT{}_PIN":"{}" }}\n'.format(i, clock[0])

            cmd += 'design.set_property("{}", pll_config, block_type="PLL")\n\n'.format(name)

        for i, clock in enumerate(block["clk_out"]):
            if block["version"] == "V1_V2":
                cmd += 'design.set_property("{}","CLKOUT{}_PHASE","{}","PLL")\n'.format(name, i, clock[2])
            else:
                cmd += 'design.set_property("{}","CLKOUT{}_PHASE_SETTING","{}","PLL")\n'.format(name, i, clock[2] // 45)

        # Titanium has always a feedback (local: CLK0, CORE: any output)
        if block["version"] == "V3":
            feedback_clk = block["feedback"]
            cmd += 'design.set_property("{}", "FEEDBACK_MODE", "{}", "PLL")\n'.format(name, "LOCAL" if feedback_clk < 1 else "CORE")
            cmd += 'design.set_property("{}", "FEEDBACK_CLK", "CLK{}", "PLL")\n'.format(name, 0 if feedback_clk < 1 else feedback_clk)

        # auto_calc_pll_clock is always working with Titanium and only working when feedback is unused for Trion
        if block["feedback"] == -1 or block["version"] == "V3":
            cmd += "target_freq = {\n"
            for i, clock in enumerate(block["clk_out"]):
                cmd += '    "CLKOUT{}_FREQ": "{}",\n'.format(i, clock[1] / 1e6)
                cmd += '    "CLKOUT{}_PHASE": "{}",\n'.format(i, clock[2])
                if clock[4] == 1:
                    cmd += '    "CLKOUT{}_DYNPHASE_EN": "1",\n'.format(i)
            cmd += "}\n"

            if block["version"] == "V1_V2":
                cmd += 'design.set_property("{}","FEEDBACK_MODE","INTERNAL","PLL")\n'.format(name)

            cmd += 'calc_result = design.auto_calc_pll_clock("{}", target_freq)\n'.format(name)
            cmd += 'for c in calc_result:\n'
            cmd += '    print(c)\n'
        else:
            cmd += 'design.set_property("{}","M","{}","PLL")\n'.format(name, block["M"])
            cmd += 'design.set_property("{}","N","{}","PLL")\n'.format(name, block["N"])
            cmd += 'design.set_property("{}","O","{}","PLL")\n'.format(name, block["O"])
            for i, clock in enumerate(block["clk_out"]):
                cmd += 'design.set_property("{}","CLKOUT{}_PHASE","{}","PLL")\n'.format(name, i, clock[2])
                #cmd += 'design.set_property("{}","CLKOUT{}_FREQ","{}","PLL")\n'.format(name, i, clock[2])
                cmd += 'design.set_property("{}","CLKOUT{}_DIV","{}","PLL")\n'.format(name, i, block[f"CLKOUT{i}_DIV"])
            cmd += 'design.set_property("{}","FEEDBACK_MODE","{}","PLL")\n'.format(name, "LOCAL" if block["feedback"] == 0 else "CORE")
            cmd += 'design.set_property("{}","FEEDBACK_CLK","CLK{}","PLL")\n'.format(name, block["feedback"])

        if "extra" in block:
            cmd += block["extra"]
            cmd += "\n"

        if verbose:
            cmd += 'print("#### {} ####")\n'.format(name)
            cmd += 'clksrc_info = design.trace_ref_clock("{}", block_type="PLL")\n'.format(name)
            cmd += 'pprint.pprint(clksrc_info)\n'
            cmd += 'clock_source_prop = ["REFCLK_SOURCE", "CORE_CLK_PIN", "EXT_CLK", "REFCLK_FREQ", "RESOURCE", "FEEDBACK_MODE", "FEEDBACK_CLK"]\n'
            for i, clock in enumerate(block["clk_out"]):
                cmd += 'clock_source_prop += ["CLKOUT{}_FREQ", "CLKOUT{}_PHASE", "CLKOUT{}_EN"]\n'.format(i, i, i)
            cmd += 'prop_map = design.get_property("{}", clock_source_prop, block_type="PLL")\n'.format(name)
            cmd += 'pprint.pprint(prop_map)\n'

            # Efinix python API is buggy for Trion devices when a feedback is defined...
            if block["version"] == "V3" or (block["version"] == "V1_V2" and block["feedback"] == -1):
                for i, clock in enumerate(block["clk_out"]):
                    cmd += '\nfreq = float(prop_map["CLKOUT{}_FREQ"])\n'.format(i)
                    cmd += 'if freq != {}:\n'.format(clock[1]/1e6)
                    cmd += '    print("ERROR: CLKOUT{} configured for {}MHz is {{}}MHz".format(freq))\n'.format(i, clock[1]/1e6)
                    cmd += '    exit("PLL ERROR")\n'

        cmd += "\n#---------- END PLL {} ---------\n\n".format(name)
        return cmd

    def generate_jtag(self, block, verbose=True):
        name = block["name"]
        id   = block["id"]
        pins = block["pins"]

        def get_pin_name(pin):
            return pin.backtrace[-1][0]

        cmds = []
        cmds.append(f"# ---------- JTAG {id} ---------")
        cmds.append(f'jtag = design.create_block("jtag_soc", block_type="JTAG")')
        cmds.append(f'design.assign_resource(jtag, "JTAG_USER{id}", "JTAG")')
        cmds.append(f'jtag_config = {{')
        cmds.append(f'    "CAPTURE" : "{get_pin_name(pins.CAPTURE)}",')
        cmds.append(f'    "DRCK"    : "{get_pin_name(pins.DRCK)}",')
        cmds.append(f'    "RESET"   : "{get_pin_name(pins.RESET)}",')
        cmds.append(f'    "RUNTEST" : "{get_pin_name(pins.RUNTEST)}",')
        cmds.append(f'    "SEL"     : "{get_pin_name(pins.SEL)}",')
        cmds.append(f'    "SHIFT"   : "{get_pin_name(pins.SHIFT)}",')
        cmds.append(f'    "TCK"     : "{get_pin_name(pins.TCK)}",')
        cmds.append(f'    "TDI"     : "{get_pin_name(pins.TDI)}",')
        cmds.append(f'    "TMS"     : "{get_pin_name(pins.TMS)}",')
        cmds.append(f'    "UPDATE"  : "{get_pin_name(pins.UPDATE)}",')
        cmds.append(f'    "TDO"     : "{get_pin_name(pins.TDO)}"')
        cmds.append(f'}}')
        cmds.append(f'design.set_property("jtag_soc", jtag_config, block_type="JTAG")')
        cmds.append(f"# ---------- END JTAG {id} ---------\n")
        return "\n".join(cmds)

    def generate_lvds(self, block, verbose=True):
        name     = block["name"]
        mode     = block["mode"]
        location = block["location"]
        size     = block["size"]
        sig      = block["sig"]
        serdes   = block.get("serdes", 1 if size > 1 else 0)
        rst_pin  = block.get("rst", "")
        delay    = block.get("delay", 0)
        cmd      = []
        fast_clk = ""
        if size > 2:
            fast_clk = block.get("fast_clk", "")
        slow_clk = block.get("slow_clk", "")
        half_rate= block.get("half_rate", "0")
        tx_output_load=block.get("output_load", "3")

        if type(slow_clk) == ClockSignal:
            slow_clk = self.platform.clks[slow_clk.cd]
        if type(fast_clk) == ClockSignal:
            fast_clk = self.platform.clks[fast_clk.cd]

        if mode == "OUTPUT":
            block_type = "LVDS_TX"
            tx_mode    = block["tx_mode"]
            oe_pin     = block.get("oe", "")
            if isinstance(oe_pin, Signal):
                oe_pin = oe_pin.name
            if isinstance(rst_pin, Signal):
                rst_pin = rst_pin.name

            cmd.append('design.create_block("{}", block_type="{}", tx_mode="{}")'.format(name, block_type, tx_mode))
            if self.platform.family == "Titanium":
                cmd.append('design.set_property("{}", "TX_DELAY",     "{}",         "{}")'.format(name, delay, block_type))
                cmd.append('design.set_property("{}", "TX_DIFF_TYPE", "LVDS",       "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "TX_HALF_RATE", "{}",         "{}")'.format(name, half_rate, block_type))
                cmd.append('design.set_property("{}", "TX_PRE_EMP",   "MEDIUM_LOW", "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "TX_VOD",       "TYPICAL",    "{}")'.format(name, block_type))
            else:
                cmd.append('design.set_property("{}", "TX_OUTPUT_LOAD",   "{}", "{}")'.format(name, tx_output_load, block_type))
                cmd.append('design.set_property("{}", "TX_REDUCED_SWING", "0", "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "TX_SLOWCLK_DIV",   "1", "{}")'.format(name, block_type))
            cmd.append('design.set_property("{}", "TX_SER",         "{}", "{}")'.format(name, size, block_type))
            cmd.append('design.set_property("{}", "TX_EN_SER",      "{}", "{}")'.format(name, serdes, block_type))
            cmd.append('design.set_property("{}", "TX_FASTCLK_PIN", "{}", "{}")'.format(name, fast_clk, block_type))
            cmd.append('design.set_property("{}", "TX_MODE",        "{}", "{}")'.format(name, tx_mode, block_type))
            cmd.append('design.set_property("{}", "TX_OE_PIN",      "{}", "{}")'.format(name, oe_pin, block_type))
            cmd.append('design.set_property("{}", "TX_OUT_PIN",     "{}", "{}")'.format(name, sig.name, block_type))
            cmd.append('design.set_property("{}", "TX_RST_PIN",     "{}", "{}")'.format(name, rst_pin, block_type))
            cmd.append('design.set_property("{}", "TX_SLOWCLK_PIN", "{}", "{}")'.format(name, slow_clk, block_type))
        else:
            block_type = "LVDS_RX"
            rx_mode    = block["rx_mode"]
            term       = block.get("term", "")
            ena        = block.get("ena", "")
            rx_delay   = block.get("rx_delay", "STATIC")
            if isinstance(term, Signal):
                term = term.name
            if isinstance(ena, Signal):
                ena = ena.name

            if rx_delay == "STATIC":
                delay_ena = ""
                delay_inc = ""
                delay_rst = ""
            else:
                delay_ena = block.get("delay_ena", "")
                delay_inc = block.get("delay_inc", "")
                delay_rst = block.get("delay_rst", "")

                if isinstance(delay_ena, Signal):
                    delay_ena = delay_ena.name
                if isinstance(delay_rst, Signal):
                    delay_rst = delay_rst.name
                if isinstance(delay_inc, Signal):
                    delay_inc = delay_inc.name

            cmd.append('design.create_block("{}", block_type="{}", rx_conn_type="{}")'.format(name, block_type, rx_mode))
            if self.platform.family == "Titanium":
                cmd.append('design.set_property("{}", "GBUF",           "",   "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "RX_DBG_PIN",     "",   "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "RX_TERM_PIN",    "{}", "{}")'.format(name, term, block_type))
                cmd.append('design.set_property("{}", "RX_VOC_DRIVER",  "0",  "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "RX_SLVS","0",    "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "RX_FIFO","0",    "{}")'.format(name, block_type))
                cmd.append('design.set_property("{}", "RX_HALF_RATE",   "{}", "{}")'.format(name, half_rate, block_type))
                cmd.append('design.set_property("{}", "RX_ENA_PIN",     "{}", "{}")'.format(name, ena, block_type))
                cmd.append('design.set_property("{}", "RX_DELAY_MODE",  "{}", "{}")'.format(name, rx_delay, block_type))
                cmd.append('design.set_property("{}", "RX_DLY_ENA_PIN", "{}", "{}")'.format(name, delay_ena, block_type))
                cmd.append('design.set_property("{}", "RX_DLY_INC_PIN", "{}", "{}")'.format(name, delay_inc, block_type))
                cmd.append('design.set_property("{}", "RX_DLY_RST_PIN", "{}", "{}")'.format(name, delay_rst, block_type))
                # Optional
                #cmd.append('design.set_property("{}", "RX_FIFOCLK_PIN",    "",                            "{}")'.format(name, block_type))
                #cmd.append('design.set_property("{}", "RX_FIFO_EMPTY_PIN", "lvds_rx_inst1_RX_FIFO_EMPTY", "{}")'.format(name, block_type))
                #cmd.append('design.set_property("{}", "RX_FIFO_RD_PIN",    "lvds_rx_inst1_RX_FIFO_RD",    "{}")'.format(name, block_type))
                #cmd.append('design.set_property("{}", "RX_LOCK_PIN",       "lvds_rx_inst1_RX_LOCK",       "{}")'.format(name, block_type))
            else:
                rx_delay = "0" if delay == 0 else "1"
                cmd.append('design.set_property("{}","RX_EN_DELAY","{}","{}")'.format(name, rx_delay, block_type))

            if not (self.platform.family == "Trion" and serdes == 0):
                cmd.append('design.set_property("{}","RX_DESER","{}","{}")'.format(name, size, block_type))
            cmd.append('design.set_property("{}", "RX_CONN_TYPE",   "{}", "{}")'.format(name, rx_mode, block_type))
            cmd.append('design.set_property("{}", "RX_DELAY",       "{}", "{}")'.format(name, delay, block_type))
            cmd.append('design.set_property("{}", "RX_EN_DESER",    "{}", "{}")'.format(name, serdes, block_type))
            cmd.append('design.set_property("{}", "RX_FASTCLK_PIN", "{}", "{}")'.format(name, fast_clk, block_type))
            cmd.append('design.set_property("{}", "RX_IN_PIN",      "{}", "{}")'.format(name, sig.name, block_type))
            cmd.append('design.set_property("{}", "RX_SLOWCLK_PIN", "{}", "{}")'.format(name, slow_clk, block_type))
            cmd.append('design.set_property("{}", "RX_TERM",        "ON", "{}")'.format(name, block_type))
            cmd.append('design.set_property("{}", "RX_RST_PIN",     "{}", "{}")'.format(name, rst_pin, block_type))

        cmd.append('design.assign_resource("{}", "{}", "{}")\n'.format(name, location, block_type))

        return '\n'.join(cmd)

    def generate_hyperram(self, block, verbose=True):
        block_type = "HYPERRAM"
        pads       = block["pads"]
        name       = block["name"]
        location   = block["location"]
        ctl_clk    = block["ctl_clk"].name_override
        cal_clk    = block["cal_clk"].name_override
        clk90_clk  = block["clk90_clk"].name_override

        cmd = []
        cmd.append('design.create_block("{}", "{}")'.format(name, block_type))
        cmd.append('design.set_property("{}", "CK_N_HI_PIN",     "{}", "{}")'.format(name, pads.clkn_h.name, block_type))
        cmd.append('design.set_property("{}", "CK_N_LO_PIN",     "{}", "{}")'.format(name, pads.clkn_l.name, block_type))
        cmd.append('design.set_property("{}", "CK_P_HI_PIN",     "{}", "{}")'.format(name, pads.clkp_h.name, block_type))
        cmd.append('design.set_property("{}", "CK_P_LO_PIN",     "{}", "{}")'.format(name, pads.clkp_l.name, block_type))
        cmd.append('design.set_property("{}", "CLK90_PIN",       "{}", "{}")'.format(name, clk90_clk, block_type))
        cmd.append('design.set_property("{}", "CLKCAL_PIN",      "{}", "{}")'.format(name, cal_clk, block_type))
        cmd.append('design.set_property("{}", "CLK_PIN",         "{}", "{}")'.format(name, ctl_clk, block_type))
        cmd.append('design.set_property("{}", "CS_N_PIN",        "{}", "{}")'.format(name, pads.csn.name, block_type))
        cmd.append('design.set_property("{}", "DQ_IN_HI_PIN",    "{}", "{}")'.format(name, pads.dq_i_h.name, block_type))
        cmd.append('design.set_property("{}", "DQ_IN_LO_PIN",    "{}", "{}")'.format(name, pads.dq_i_l.name, block_type))
        cmd.append('design.set_property("{}", "DQ_OE_PIN",       "{}", "{}")'.format(name, pads.dq_oe.name, block_type))
        cmd.append('design.set_property("{}", "DQ_OUT_HI_PIN",   "{}", "{}")'.format(name, pads.dq_o_h.name, block_type))
        cmd.append('design.set_property("{}", "DQ_OUT_LO_PIN",   "{}", "{}")'.format(name, pads.dq_o_l.name, block_type))
        cmd.append('design.set_property("{}", "RST_N_PIN",       "{}", "{}")'.format(name, pads.rstn.name, block_type))
        cmd.append('design.set_property("{}", "RWDS_IN_HI_PIN",  "{}", "{}")'.format(name, pads.rwds_i_h.name, block_type))
        cmd.append('design.set_property("{}", "RWDS_IN_LO_PIN",  "{}", "{}")'.format(name, pads.rwds_i_l.name, block_type))
        cmd.append('design.set_property("{}", "RWDS_OE_PIN",     "{}", "{}")'.format(name, pads.rwds_oe.name, block_type))
        cmd.append('design.set_property("{}", "RWDS_OUT_HI_PIN", "{}", "{}")'.format(name, pads.rwds_o_h.name, block_type))
        cmd.append('design.set_property("{}", "RWDS_OUT_LO_PIN", "{}", "{}")'.format(name, pads.rwds_o_l.name, block_type))

        cmd.append('design.assign_resource("{}", "{}", "{}")\n'.format(name, location, block_type))

        return '\n'.join(cmd) + '\n'

    def generate_spiflash(self, block, verbose=True):
        pads       = block["pads"]
        name       = block["name"]
        location   = block["location"]
        mode       = block["mode"]

        assert mode in ["x1"] # FIXME: support x4
        assert location == "SPI_FLASH0"

        dq0 = pads.mosi.name
        dq1 = pads.miso.name
        dq2 = pads.wp.name
        dq3 = pads.hold.name

        cmd = []
        cmd.append('design.create_block("{}", "SPI_FLASH")'.format(name))
        cmd.append('design.set_property("{}", "MULT_CTRL_EN", "0",  "SPI_FLASH")'.format(name))
        cmd.append('design.set_property("{}", "REG_EN",       "0",  "SPI_FLASH")'.format(name))
        cmd.append('design.set_property("{}", "CLK_PIN",      "",   "SPI_FLASH")'.format(name)) # only required when REG_EN==1
        cmd.append('design.set_property("{}", "RW_WIDTH",     "{}", "SPI_FLASH")'.format(name, mode))

        cmd.append('design.set_property("{}", "CS_N_OUT_PIN",   "{}", "SPI_FLASH")'.format(name, pads.cs_n.name))
        cmd.append('design.set_property("{}", "SCLK_OUT_PIN",   "{}", "SPI_FLASH")'.format(name, pads.clk.name))
        cmd.append('design.set_property("{}", "MOSI_OUT_PIN",   "{}", "SPI_FLASH")'.format(name, dq0))
        cmd.append('design.set_property("{}", "MISO_IN_PIN",    "{}", "SPI_FLASH")'.format(name, dq1))
        cmd.append('design.set_property("{}", "WP_N_OUT_PIN",   "{}", "SPI_FLASH")'.format(name, dq2))
        cmd.append('design.set_property("{}", "HOLD_N_OUT_PIN", "{}", "SPI_FLASH")'.format(name, dq3))

        if mode == "x4":
            cmd.append('design.set_property("{}", "HOLD_N_IN_PIN", "{}", "SPI_FLASH")'.format(name, dq3_i))
            cmd.append('design.set_property("{}", "HOLD_N_OE_PIN", "{}", "SPI_FLASH")'.format(name, dq3_oe))
            cmd.append('design.set_property("{}", "MISO_OUT_PIN",  "{}", "SPI_FLASH")'.format(name, dq1_o))
            cmd.append('design.set_property("{}", "MISO_OE_PIN",   "{}", "SPI_FLASH")'.format(name, dq1_oe))
            cmd.append('design.set_property("{}", "MOSI_IN_PIN",   "{}", "SPI_FLASH")'.format(name, dq0_i))
            cmd.append('design.set_property("{}", "MOSI_OE_PIN",   "{}", "SPI_FLASH")'.format(name, dq0_oe))
            cmd.append('design.set_property("{}", "WP_N_IN_PIN",   "{}", "SPI_FLASH")'.format(name, dq2_i))
            cmd.append('design.set_property("{}", "WP_N_OE_PIN",   "{}", "SPI_FLASH")'.format(name, dq2_oe))

        # mult ctrl en only
        #cmd.append('design.set_property("{}", "CS_N_OE_PIN","{}","SPI_FLASH")'.format(name, cs_n_oe))
        #cmd.append('design.set_property("{}", "SCLK_OE_PIN","{}","SPI_FLASH")'.format(name, clk_oe))

        cmd.append('design.assign_resource("{}", "{}","SPI_FLASH")\n'.format(name, location))

        cmd.append('design.set_device_property("ext_flash","EXT_FLASH_CTRL_EN","0","EXT_FLASH")')

        return '\n'.join(cmd) + '\n'

    def generate_remote_update(self, block, verbose=True):
        name = block["name"]
        pins = block["pins"]
        clock = block["clock"]
        invert_clk = block["invert_clock"]
        enable = block["enable"]

        def get_pin_name(pin):
            return pin.backtrace[-1][0]

        cmds = []
        cmds.append(f"# ---------- REMOTE UPDATE ---------")
        cmds.append(f'design.set_device_property("ru", "RECONFIG_EN", "{enable}", "RU")')
        if enable:
            cmds.append(f'design.set_device_property("ru", "CBSEL_PIN", "{get_pin_name(pins.CBSEL)}", "RU")')
            cmds.append(f'design.set_device_property("ru", "CLK_PIN", "{clock}", "RU")')
            cmds.append(f'design.set_device_property("ru", "CONFIG_PIN", "{get_pin_name(pins.CONFIG)}", "RU")')
            cmds.append(f'design.set_device_property("ru", "ENA_PIN", "{get_pin_name(pins.ENA)}", "RU")')
            cmds.append(f'design.set_device_property("ru", "ERROR_PIN", "{get_pin_name(pins.ERROR)}", "RU")')
            if hasattr(pins, 'IN_USER'):
                cmds.append(f'design.set_device_property("ru", "IN_USER_PIN", "{get_pin_name(pins.IN_USER)}", "RU")')
            cmds.append(f'design.set_device_property("ru", "INVERT_CLK_EN", "{invert_clk}", "RU")')
        cmds.append(f"# ---------- END REMOTE UPDATE ---------\n")
        return "\n".join(cmds)

    def generate_seu(self, block, verbose=True):
        name = block["name"]
        pins = block["pins"]
        enable = block["enable"]
        mode = block["mode"].upper()

        def get_pin_name(pin):
            return pin.backtrace[-1][0]

        cmds = []
        cmds.append(f"# ---------- SINGLE-EVENT UPSET ---------")
        cmds.append(f'design.set_device_property("seu", "ENA_DETECT", "{enable}", "SEU")')
        if enable:
            cmds.append(f'design.set_device_property("seu", "CONFIG_PIN", "{get_pin_name(pins.CONFIG)}", "SEU")')
            cmds.append(f'design.set_device_property("seu", "DONE_PIN", "{get_pin_name(pins.DONE)}", "SEU")')
            cmds.append(f'design.set_device_property("seu", "ERROR_PIN", "{get_pin_name(pins.ERROR)}", "SEU")')
            cmds.append(f'design.set_device_property("seu", "INJECT_ERROR_PIN", "{get_pin_name(pins.INJECT_ERROR)}", "SEU")')
            cmds.append(f'design.set_device_property("seu", "RST_PIN", "{get_pin_name(pins.RST)}", "SEU")')
            if mode == "MANUAL":
                cmds.append(f'design.set_device_property("seu", "START_PIN", "{get_pin_name(pins.START)}", "SEU")')
            cmds.append(f'design.set_device_property("seu", "MODE", "{mode}", "SEU")')
            if mode == "AUTO" and hasattr(block, "wait_interval"):
                cmds.append(f'design.set_device_property("seu", "WAIT_INTERVAL", "{block["wait_interval"]}", "SEU")')
        cmds.append(f"# ---------- END SINGLE-EVENT UPSET ---------\n")
        return "\n".join(cmds)

    def generate(self, partnumber):
        output = ""
        for block in self.blocks:
            if isinstance(block, InterfaceWriterBlock):
                output += block.generate()
            else:
                if block["type"] == "PLL":
                    output += self.generate_pll(block, partnumber)
                if block["type"] == "GPIO":
                    output += self.generate_gpio(block)
                if block["type"] == "MIPI_TX_LANE":
                    output += self.generate_mipi_tx(block)
                if block["type"] == "MIPI_RX_LANE":
                    output += self.generate_mipi_rx(block)
                if block["type"] == "LVDS":
                    output += self.generate_lvds(block)
                if block["type"] == "HYPERRAM":
                    output += self.generate_hyperram(block)
                if block["type"] == "JTAG":
                    output += self.generate_jtag(block)
                if block["type"] == "SPI_FLASH":
                    output += self.generate_spiflash(block)
                if block["type"] == "REMOTE_UPDATE":
                    output += self.generate_remote_update(block)
                if block["type"] == "SEU":
                    output += self.generate_seu(block)
        return output

    def footer(self):
        return """
# Check design, generate constraints and reports
design.generate(enable_bitstream=True)
# Save the configured periphery design
design.save()"""
