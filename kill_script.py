import os
import signal
import psutil

def kill_all_python_procs():
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower() or (proc.info['cmdline'] and 'src' in ' '.join(proc.info['cmdline'])):
                if proc.info['pid'] != current_pid:
                    print(f"Killing process {proc.info['pid']}: {proc.info['cmdline']}")
                    os.kill(proc.info['pid'], signal.SIGKILL)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

if __name__ == "__main__":
    kill_all_python_procs()
