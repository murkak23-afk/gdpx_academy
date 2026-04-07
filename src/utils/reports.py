import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=3)

def sync_report_gen_function(data):
    # sync code: openpyxl, csv, etc.
    ...

async def generate_report_async(data):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, sync_report_gen_function, data)
