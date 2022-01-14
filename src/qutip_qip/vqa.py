import numpy as np
from qutip import basis, tensor, Qobj
from qutip.qip.circuit import QubitCircuit, Gate, Measurement
from qutip_qip.operations import *
from scipy.optimize import minimize
from qutip_qip.qaoa import state_probs_plot

def sample_bitstring_from_state(state):
    """
    Uses probability amplitudes from state in computational
    basis to sample a bitstring.
    E.g. the state 1/sqrt(2) * (|0> + |1>)
    would return 0 and 1 with equal probability.
    """
    n_qbits = int(np.log2(state.shape[0]))
    outcome_indices = [i for i in range(2**n_qbits)]
    probs = [abs(i.item())**2 for i in state]
    outcome_index = np.random.choice(outcome_indices, p=probs)
    return format(outcome_index, f'0{n_qbits}b')
def highest_prob_bitstring(state):
    """
    Returns the bitstring associated with the
    highest probability amplitude state (computational basis).
    """
    n_qbits = int(np.log2(state.shape[0]))
    index = np.argmax(abs(state))
    return format(index, f'0{n_qbits}b')

class VQA:
    def __init__(self, n_qubits, n_layers=1, cost_method="BITSTRING"):
        # defaults for now
        self.n_qubits = n_qubits
        self.n_layers = n_layers
        self.blocks = []
        self.user_gates = {}
        self._cost_methods = ["OBSERVABLE", "STATE", "BITSTRING"]
        self.cost_method = cost_method
        self.cost_func = None
        self.cost_observable = None
    def add_block(self, block):
        if not block.name:
            block.name = "U" + str(len(self.blocks))
        if block.name in list(map(lambda b: b.name, self.blocks)):
            raise ValueError("Duplicate Block name in self.blocks")
        self.blocks.append(block)
        self.user_gates[block.name] = lambda theta=None: block.get_unitary(theta)
    def get_free_parameters(self):
        """
        Computes the number of free parameters required
        to evaluate the circuit.

        Returns
        -------
        num_params : int
            number of free parameters
        """
        initial_free_params = len(list(filter(
            lambda b: 
                not (b.is_unitary or b.is_native_gate) 
                and b.initial,
            self.blocks
            )))
        layer_free_params = len(list(filter(
            lambda b: 
                not (b.is_unitary or b.is_native_gate) 
                and not b.initial,
            self.blocks
            ))) * self.n_layers

        return initial_free_params + layer_free_params
 
    def construct_circuit(self, thetas):
        circ = QubitCircuit(self.n_qubits)
        circ.user_gates = self.user_gates
        i = 0
        for layer_num in range(self.n_layers):
            for block in self.blocks:
                if block.initial and layer_num > 0:
                    continue
                if block.is_native_gate:
                    circ.add_gate(block.operator, targets=block.targets)
                elif block.is_unitary:
                    circ.add_gate(block.name, targets=[i for i in range(self.n_qubits)])
                else:
                    circ.add_gate(block.name, arg_value=thetas[i], targets=[i for i in range(self.n_qubits)])
                    i += 1
        return circ
    def get_initial_state(self):
        """
        Returns the initial circuit state
        """
        initial_state = basis(2, 0)
        for i in range(self.n_qubits - 1):
            initial_state = tensor(initial_state, basis(2, 0))
        return initial_state
    def get_final_state(self, thetas):
        """
        Returns final state of circuit from initial state
        """
        circ = self.construct_circuit(thetas)
        initial_state = self.get_initial_state()
        final_state = circ.run(initial_state)
        return final_state
    def evaluate_parameters(self, thetas):
        """
        Constructs a circuit with given parameters
        and returns a cost from evaluating the circuit
        """
        final_state = self.get_final_state(thetas)
        if self.cost_method == "BITSTRING":
            if self.cost_func == None:
                raise ValueError("self.cost_func not specified")
            return self.cost_func(highest_prob_bitstring(final_state))
        elif self.cost_method == "STATE":
            raise Exception("NOT IMPLEMENTED")
        elif self.cost_method == "OBSERVABLE":
            """
            Cost as expectation of observable in in state final_state
            """
            if self.cost_observable == None:
                raise ValueError("self.cost_observable not specified")
            #print(self.cost_observable)
            cost = final_state.dag() * self.cost_observable * final_state
            return abs(cost[0].item())
    def optimise_parameters(self):
        # TODO: initialise this better
        INITIAL_PARAM = 1
        thetas = [INITIAL_PARAM for i in range(self.get_free_parameters())]
        res = minimize(
                self.evaluate_parameters, 
                thetas,
                method='COBYLA'
                )
        thetas = res.x
        final_state = self.get_final_state(thetas)
        result = Optimization_Result(res, final_state)
        return result
        
    def export_image(self, filename="circuit.png"):
        circ = self.construct_circuit([1])
        f = open(filename, 'wb+')
        f.write(circ.png)
        f.close()
        print(f"Image saved to ./{filename}")


class VQA_Block:
    """
    A "Block" is a constitutent part of a "layer".
    containing a single Hamiltonian or Unitary
    specified by the user. In the case that a Unitary
    is given, there is no associated circuit parameter
    for the block.
    If the operator is given as a string, it assumed
    to reference a default qutip_qip.operations gate.
    A "layer" is given by the product of all blocks.
    """
    def __init__(self, operator, is_unitary=False, name=None, targets=None, initial=False):
        self.operator = operator
        self.is_unitary = is_unitary
        self.name = name
        self.targets = targets
        self.is_native_gate = isinstance(operator, str)
        self.initial = initial
        if self.is_native_gate:
            if targets == None:
                raise ValueError("Targets must be specified for native gates")
        else:
            if not isinstance(operator, Qobj):
                raise ValueError("Operator given was neither a gate name nor Qobj")
    def get_unitary(self, theta=None):
        if self.is_unitary:
            return self.operator
        else:
            if theta == None:
                # TODO: raise better exception?
                raise TypeError("No parameter given")
            return (-1j * theta * self.operator).expm()

class Optimization_Result:
    def __init__(self, res, final_state):
        """
        res : scipy optimisation result object
        """
        self.res = res
        self.thetas = res.x
        self.min_cost = res.fun
        self.nfev = res.nfev
        self.final_state = final_state
    def get_top_bitstring(self):
        return "|" + highest_prob_bitstring(self.final_state) + ">"
    def __str__(self):
        return "Optimization Result:\n" +             \
                f"\tMinimum cost: {self.min_cost}\n" +  \
                f"\tNumber of function evaluations: {self.nfev}\n" + \
                f"\tParameters found: {self.thetas}"
    def plot(self, S):
        state_probs_plot(self.final_state, S)
