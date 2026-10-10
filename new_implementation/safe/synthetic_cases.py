#!/usr/bin/env python3
"""Synthetic Golden/mutant pairs with known-correct answers.

These exist so the formal witness pipeline can be judged against ground truth
before it is pointed at the benchmark. Each case is small, hand-written, and has
a documented distinguishing input, so a failure is unambiguously the pipeline's
fault rather than the design's.

Every case declares `expect`: SAT means a distinguishing input sequence provably
exists, and the pipeline must find and replay it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Case:
    name: str
    family: str
    golden: str
    mutant: str
    expect: str                     # "SAT"
    witness_hint: str               # how a human would distinguish them
    clock: Optional[str] = None
    reset: Optional[str] = None
    reset_active: int = 1
    reset_sync: bool = True
    inputs: Dict[str, int] = None   # name -> width
    outputs: Dict[str, int] = None


def _c(**kw) -> Case:
    kw.setdefault("inputs", {})
    kw.setdefault("outputs", {})
    return Case(**kw)


CASES: List[Case] = [

    _c(name="comb_operator", family="combinational",
       inputs={"a": 1, "b": 1}, outputs={"y": 1}, expect="SAT",
       witness_hint="a=1,b=0 gives 1 for OR and 0 for AND",
       golden="""module top_module(input a, input b, output y);
  assign y = a | b;
endmodule""",
       mutant="""module top_module(input a, input b, output y);
  assign y = a & b;
endmodule"""),

    _c(name="counter_free", family="counter", clock="clk",
       inputs={}, outputs={"q": 4}, expect="SAT",
       witness_hint="after one clock, golden is 1 and mutant is 15",
       golden="""module top_module(input clk, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) q <= q + 1;
endmodule""",
       mutant="""module top_module(input clk, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) q <= q - 1;
endmodule"""),

    _c(name="counter_wrap", family="counter", clock="clk",
       inputs={}, outputs={"q": 4}, expect="SAT",
       witness_hint="differs only at the 10th cycle, where golden wraps to 0",
       golden="""module top_module(input clk, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) q <= (q == 9) ? 4'd0 : q + 1;
endmodule""",
       mutant="""module top_module(input clk, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) q <= (q == 15) ? 4'd0 : q + 1;
endmodule"""),

    _c(name="counter_enable", family="counter", clock="clk",
       inputs={"en": 1}, outputs={"q": 4}, expect="SAT",
       witness_hint="en=0 holds in golden but still counts in mutant",
       golden="""module top_module(input clk, input en, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) if (en) q <= q + 1;
endmodule""",
       mutant="""module top_module(input clk, input en, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) q <= q + 1;
endmodule"""),

    _c(name="reset_sync_high", family="reset", clock="clk", reset="rst",
       reset_active=1, reset_sync=True,
       inputs={"rst": 1}, outputs={"q": 4}, expect="SAT",
       witness_hint="rst=1 clears golden, mutant treats it as inactive",
       golden="""module top_module(input clk, input rst, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) if (rst) q <= 0; else q <= q + 1;
endmodule""",
       mutant="""module top_module(input clk, input rst, output reg [3:0] q);
  initial q = 0;
  always @(posedge clk) if (!rst) q <= 0; else q <= q + 1;
endmodule"""),

    _c(name="reset_async_low", family="reset", clock="clk", reset="rst_n",
       reset_active=0, reset_sync=False,
       inputs={"rst_n": 1, "d": 1}, outputs={"q": 1}, expect="SAT",
       witness_hint="async clear takes effect between edges; sync version does not",
       golden="""module top_module(input clk, input rst_n, input d, output reg q);
  initial q = 0;
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else q <= d;
endmodule""",
       mutant="""module top_module(input clk, input rst_n, input d, output reg q);
  initial q = 0;
  always @(posedge clk) if (!rst_n) q <= 0; else q <= d;
endmodule"""),

    _c(name="fsm_small", family="fsm", clock="clk", reset="rst",
       reset_active=1, reset_sync=True,
       inputs={"rst": 1, "x": 1}, outputs={"z": 1}, expect="SAT",
       witness_hint="one transition destination changed; needs 2-3 cycles to expose",
       golden="""module top_module(input clk, input rst, input x, output z);
  reg [1:0] s;
  initial s = 0;
  always @(posedge clk) begin
    if (rst) s <= 0;
    else case (s)
      2'd0: s <= x ? 2'd1 : 2'd0;
      2'd1: s <= x ? 2'd2 : 2'd0;
      2'd2: s <= x ? 2'd2 : 2'd3;
      default: s <= 2'd0;
    endcase
  end
  assign z = (s == 2'd3);
endmodule""",
       mutant="""module top_module(input clk, input rst, input x, output z);
  reg [1:0] s;
  initial s = 0;
  always @(posedge clk) begin
    if (rst) s <= 0;
    else case (s)
      2'd0: s <= x ? 2'd1 : 2'd0;
      2'd1: s <= x ? 2'd2 : 2'd0;
      2'd2: s <= x ? 2'd2 : 2'd0;
      default: s <= 2'd0;
    endcase
  end
  assign z = (s == 2'd3);
endmodule"""),

    _c(name="multibit_input", family="datapath",
       inputs={"a": 4, "b": 4}, outputs={"s": 5}, expect="SAT",
       witness_hint="operand truncated to 3 bits; a=8 exposes it",
       golden="""module top_module(input [3:0] a, input [3:0] b, output [4:0] s);
  assign s = a + b;
endmodule""",
       mutant="""module top_module(input [3:0] a, input [3:0] b, output [4:0] s);
  assign s = a[2:0] + b;
endmodule"""),

    _c(name="multibit_output", family="datapath", clock="clk",
       inputs={"d": 8}, outputs={"q": 8}, expect="SAT",
       witness_hint="shift direction reversed; any asymmetric d exposes it",
       golden="""module top_module(input clk, input [7:0] d, output reg [7:0] q);
  initial q = 0;
  always @(posedge clk) q <= d << 1;
endmodule""",
       mutant="""module top_module(input clk, input [7:0] d, output reg [7:0] q);
  initial q = 0;
  always @(posedge clk) q <= d >> 1;
endmodule"""),

    _c(name="no_reset_seq", family="no_reset", clock="clk",
       inputs={"d": 1}, outputs={"q": 1}, expect="SAT",
       witness_hint="no reset port; golden registers d, mutant registers ~d",
       golden="""module top_module(input clk, input d, output reg q);
  initial q = 0;
  always @(posedge clk) q <= d;
endmodule""",
       mutant="""module top_module(input clk, input d, output reg q);
  initial q = 0;
  always @(posedge clk) q <= ~d;
endmodule"""),
]


def by_name(name: str) -> Case:
    for c in CASES:
        if c.name == name:
            return c
    raise KeyError(name)
