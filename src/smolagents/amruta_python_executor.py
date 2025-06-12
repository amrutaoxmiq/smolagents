
from .local_python_executor import PythonExecutor
from typing import Any
from .tools import Tool
import logging
from typing import Optional
import re

class FinalAnswerException(Exception):
    """Exception raised when final_answer() is called to terminate execution."""
    def __init__(self, value):
        self.value = value

class AmrutaPythonExecutor(PythonExecutor):
    def __init__(self):
        # Initialize state to track print outputs
        self.state = {"__name__": "__main__"}
        self.static_tools = None
        self.final_answer_pattern = re.compile(r"^\s*final_answer\((.*)\)$", re.M)

    def __call__(self, code: str) -> tuple[Any, str, bool]:
        """
        Execute a Python file in a virtual environment with specified requirements.
        
        Args:
            code (str): Python code to execute
            requirements (list[str]): List of Python requirements for code
            
        Returns:
            tuple: (execution_output, logs, is_final_answer)
        """        
        if self.static_tools and "final_answer" in self.static_tools:
            previous_final_answer = self.static_tools["final_answer"]

            def final_answer(*args, **kwargs):
                # Call the original final_answer tool and raise exception with result
                raise FinalAnswerException(previous_final_answer(*args, **kwargs))

            # Replace the final_answer tool with our wrapped version
            self.static_tools["final_answer"] = final_answer

        output = None
        logs = None
        is_final_answer = False
        try:
            # Create execution environment with tools available as functions
            exec_globals = self.state.copy()
            if self.static_tools:
                exec_globals.update(self.static_tools)
            
            # Execute the code
            exec(code, exec_globals)
            
            # Update state with any new variables created during execution
            self.state.update({k: v for k, v in exec_globals.items() 
                             if k not in self.static_tools and not k.startswith('__')})
            
        except FinalAnswerException as e:
            # final_answer() was called - extract the result and mark as final
            output = e.value
            is_final_answer = True
            logs = "final_answer() called - execution terminated"
            
        except Exception as e:
            # Other execution errors
            logs = f"Execution error: {type(e).__name__}: {e}"
            output = None

        return output, logs, is_final_answer
    
    def send_variables(self, variables: dict):
        self.state.update(variables)

    def send_tools(self, tools: dict[str, Tool]):
        # Combine agent tools, base Python tools, and additional Python functions
        self.static_tools = {**tools}