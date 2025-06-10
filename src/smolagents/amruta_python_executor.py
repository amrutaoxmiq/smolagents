import os
import sys
import subprocess
import shlex
import fcntl
import time
import select
from .local_python_executor import PythonExecutor
from typing import Any
from .tools import Tool
import logging
from typing import Optional

def setup_venv(requirements, venv_name=None):
    """
    Set up and activate a Python virtual environment with packages from a requirements file.
    
    Args:
        requirements (list[str]): List of Python requirements for code
        venv_name (str, optional): Name for the virtual environment. If not provided,
                                  it will be derived from the requirements filename.
    
    Returns:
        str: Path to the created/existing virtual environment
    """
    # Validate requirements
    if not requirements or not isinstance(requirements, list):
        print("Error: Requirements must be a non-empty list of package names!")
        sys.exit(1)
    
    # Determine venv name if not provided
    if venv_name is None:
        base_name = os.path.basename(os.getcwd())
        venv_name = base_name + "_venv"
    
    venv_path = os.path.abspath(venv_name)
    
    # Check if virtual environment already exists
    venv_exists = os.path.isdir(venv_path) and (
        os.path.isfile(os.path.join(venv_path, "bin", "activate")) # Unix/Mac
    )
    
    # Create virtual environment if it doesn't exist
    if not venv_exists:
        print(f"Creating virtual environment in '{venv_path}'...")
        try:
            subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
        except subprocess.CalledProcessError:
            print("Failed to create virtual environment!")
            sys.exit(1)
    else:
        print(f"Using existing virtual environment in '{venv_path}'")
    
    pip_exe = os.path.join(venv_path, "bin", "pip")
    
     # Install requirements
    print(f"Installing packages: {', '.join(requirements)}...")
    try:
        # Install each package directly
        subprocess.run([pip_exe, "install"] + requirements, check=True)
        print("Package installation completed successfully!")
    except subprocess.CalledProcessError:
        print("Failed to install packages!")
        sys.exit(1)
    
    
    return venv_path

def run_in_venv(venv_path, code, timeout=30):
    """
    Run a Python file within the specified virtual environment and capture output.
    
    Args:
        venv_path (str): Path to the virtual environment
        code (str): Python code to run
        timeout (int): Maximum execution time in seconds
        
    Returns:
        tuple: (stdout_content, stderr_content, return_code)
    """
    if code is None:
        raise ValueError("The code must be provided")

    # Build paths
    activate_script = os.path.join(venv_path, "bin", "activate")
    if not os.path.isfile(activate_script):
        raise FileNotFoundError(f"Virtual environment activation script not found at '{activate_script}'")

    # Properly quote file paths
    activate_script_quoted = shlex.quote(activate_script)

    # Build shell command
    full_command = f'source {activate_script_quoted} && python3 -c {shlex.quote(code)}'
    
    print(f"Running command in shell: {full_command}")
    
    process = subprocess.Popen(['/bin/bash', '-c', full_command],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              bufsize=0)
    
    # Set non-blocking mode
    fd_out = process.stdout.fileno()
    flags = fcntl.fcntl(fd_out, fcntl.F_GETFL)
    fcntl.fcntl(fd_out, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    fd_err = process.stderr.fileno()
    flags = fcntl.fcntl(fd_err, fcntl.F_GETFL)
    fcntl.fcntl(fd_err, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    stdout_data = []
    stderr_data = []
    buffer_size = 48
    start_time = time.time()

    while True:
        # Check timeout
        if time.time() - start_time > timeout:
            process.kill()
            return "", f"Execution timed out after {timeout} seconds", -1
        
        ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)

        if process.stdout in ready:
            chunk = process.stdout.read(buffer_size)
            if chunk:
                stdout_data.append(chunk.decode())

        if process.stderr in ready:
            chunk = process.stderr.read(buffer_size)
            if chunk:
                stderr_data.append(chunk.decode())

        # Check if process is done
        poll_result = process.poll()
        if poll_result is not None:
            # Read any remaining data
            for fd, data_list in [(process.stdout, stdout_data), (process.stderr, stderr_data)]:
                while True:
                    try:
                        chunk = fd.read(buffer_size)
                        if not chunk:
                            break
                        data_list.append(chunk.decode())
                    except:
                        break
            break

    # Close the process
    process.stdout.close()
    process.stderr.close()
    return_code = process.wait()
    
    return ''.join(stdout_data), ''.join(stderr_data), return_code


def executor(code: str, requirements: Optional[list[str]]) -> str:
    """
    Execute Python code in a virtual environment with specified requirements.
    
    Args:
        code (str): Python code to execute
        requirements (list[str]): List of Python requirements for code
    
    Returns:
        str: Execution result including stdout, stderr, and status
    """
    print("&8%$")
    try:
        if requirements is None: requirements = []

        # Setup virtual environment
        venv_path = setup_venv(requirements, "env1")
        
        # Execute the code and capture output
        stdout_content, stderr_content, return_code = run_in_venv(venv_path, code, timeout=60)
        
        # Format the result for the LLM
        result = []
        result.append(f"=== EXECUTION RESULT ===")
        result.append(f"Return Code: {return_code}")
        
        if stdout_content:
            result.append(f"\n--- STDOUT ---")
            result.append(stdout_content)
        
        if stderr_content:
            result.append(f"\n--- STDERR ---")
            result.append(stderr_content)
        
        if return_code == 0:
            result.append(f"\n✅ Execution completed successfully!")
        else:
            result.append(f"\n❌ Execution failed with return code {return_code}")
        
        # Also write to files for debugging (optional)
        with open("stdout.txt", 'w') as f:
            f.write(stdout_content)
        with open("stderr.txt", 'w') as f:
            f.write(stderr_content)
        
        return '\n'.join(result)
        
    except Exception as e:
        return f"❌ Executor error: {str(e)}"


class AmrutaPythonExecutor(PythonExecutor):
    def __init__(self):
        # Initialize state to track print outputs
        self.state = {"_print_outputs": ""}

    def __call__(self, code: str, requirements: Optional[list[str]]) -> tuple[Any, str, bool]:
        """
        Execute a Python file in a virtual environment with specified requirements.
        
        Args:
            code (str): Python code to execute
            requirements (list[str]): List of Python requirements for code
            
        Returns:
            tuple: (execution_output, logs, is_final_answer)
        """        
        # Execute the code and get the result
        output = executor(code, requirements)
        
        # Extract logs from the state (print outputs during execution)
        logs = str(self.state["_print_outputs"])
        
        # Determine if this is a final answer (you may need to adjust this logic)
        # For now, assuming it's not a final answer unless the execution was successful
        is_final_answer = "✅ Execution completed successfully!" in output
        
        return output, logs, is_final_answer
    
    def send_variables(self, variables: dict):
        self.state.update(variables)

    def send_tools(self, tools: dict[str, Tool]):
        # Combine agent tools, base Python tools, and additional Python functions
        self.static_tools = {**tools}