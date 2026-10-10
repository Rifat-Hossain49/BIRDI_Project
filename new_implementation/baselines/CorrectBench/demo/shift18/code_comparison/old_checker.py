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