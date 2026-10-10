class GoldenDUT:
    def __init__(self):
        # Initialize internal state register
        self.q_reg = 0
        
    def load(self, signal_vector):
        # Load the input signals and update the internal state
        load = signal_vector['load']
        ena = signal_vector['ena']
        data = signal_vector['data']
        amount = signal_vector['amount']
        current_q = self.q_reg
        
        if load:
            # Load data into the shift register
            self.q_reg = data & 0xFFFFFFFFFFFFFFFF  # Ensure 64-bit width
        elif ena:
            if amount == 0b00:
                # Shift left by 1
                self.q_reg = (current_q << 1) & 0xFFFFFFFFFFFFFFFF
            elif amount == 0b01:
                # Shift left by 8
                self.q_reg = (current_q << 8) & 0xFFFFFFFFFFFFFFFF
            elif amount == 0b10:
                # Arithmetic shift right by 1
                self.q_reg = (current_q >> 1) | ((current_q & 0x8000000000000000) >> 1)
            elif amount == 0b11:
                # Arithmetic shift right by 8
                self.q_reg = (current_q >> 8) | ((current_q & 0x8000000000000000) >> 8)
        
    def check(self, signal_vector):
        # Check expected and observed output values
        q_observed = signal_vector['q']
        q_expected = self.q_reg
        
        if q_expected == q_observed:
            return True
        else:
            print(f"Scenario: {signal_vector['scenario']}, expected: q={q_expected}, observed q={q_observed}")
            return False

def check_dut(vectors_in):
    golden_dut = GoldenDUT()
    failed_scenarios = []
    for vector in vectors_in:
        if vector["check_en"]:
            check_pass = golden_dut.check(vector)
            if check_pass:
                print(f"Passed; vector: {vector}")
            else:
                print(f"Failed; vector: {vector}")
                failed_scenarios.append(vector["scenario"])
        golden_dut.load(vector)
    return failed_scenarios

def SignalTxt_to_dictlist(txt:str):
    signals = []
    lines = txt.strip().split("\n")
    for line in lines:
        signal = {}
        if line.startswith("[check]"):
            signal["check_en"] = True
            line = line[7:]
        elif line.startswith("scenario"):
            signal["check_en"] = False
        else:
            continue
        line = line.strip().split(", ")
        for item in line:
            if "scenario" in item:
                item = item.split(": ")
                signal["scenario"] = item[1].replace(" ", "")
            else:
                item = item.split(" = ")
                key = item[0]
                value = item[1]
                if ("x" not in value) and ("X" not in value) and ("z" not in value):
                    signal[key] = int(value)
                else:
                    if ("x" in value) or ("X" in value):
                        signal[key] = 0 # used to be "x"
                    else:
                        signal[key] = 0 # used to be "z"
        signals.append(signal)
    return signals
with open("TBout.txt", "r") as f:
    txt = f.read()
vectors_in = SignalTxt_to_dictlist(txt)
tb_pass = check_dut(vectors_in)
print(tb_pass)
