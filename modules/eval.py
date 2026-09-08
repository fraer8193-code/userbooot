import sys
import io
import time
import asyncio
import traceback
import subprocess
from telethon import events
import core

@core.command("eval", description="Execute Python code", usage=".eval <code>")
async def eval_cmd(event: events.NewMessage.Event):
    """Executes arbitrary Python code asynchronously and prints stdout/result."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.edit("Использование: `.eval <code>`")
        return

    code = args[1].strip()
    await event.edit("Executing...")

    # Перехват стандартного вывода
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    redirected_output = sys.stdout = io.StringIO()
    redirected_error = sys.stderr = io.StringIO()
    
    stdout, stderr, exc = None, None, None
    start_time = time.time()

    async def aexec(code, event):
        exec(
            f"async def __aexec(event, client, chat_id):\n"
            + "".join(f"    {line}\n" for line in code.split("\n")),
            globals(),
            locals()
        )
        return await locals()["__aexec"](event, event.client, event.chat_id)

    try:
        returned = await aexec(code, event)
    except Exception:
        exc = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout = redirected_output.getvalue()
    stderr = redirected_error.getvalue()
    elapsed = (time.time() - start_time) * 1000

    out = ""
    if exc:
        out = f"**Error:**\n```{exc}```"
    elif stderr:
        out = f"**Stderr:**\n```{stderr}```"
    elif stdout:
        out = f"**Output:**\n```{stdout}```"
    elif returned is not None:
        out = f"**Result:**\n```{repr(returned)}```"
    else:
        out = "**Success** (No output)"

    out += f"\nTime: `{elapsed:.2f} ms`"
    await event.edit(out)

@core.command("term", description="Run shell/terminal command", usage=".term <command>")
async def term_cmd(event: events.NewMessage.Event):
    """Executes a system shell command and returns output."""
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.edit("Использование: `.term <command>`")
        return

    cmd = args[1].strip()
    await event.edit("Running terminal...")
    start_time = time.time()

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_b, stderr_b = await proc.communicate()
        elapsed = (time.time() - start_time) * 1000

        stdout = stdout_b.decode("utf-8", errors="replace").strip()
        stderr = stderr_b.decode("utf-8", errors="replace").strip()

        res = ""
        if stdout:
            res += f"**Output:**\n```{stdout}```\n"
        if stderr:
            res += f"**Stderr:**\n```{stderr}```\n"
        if not stdout and not stderr:
            res = "**Success** (No output)\n"

        res += f"Time: `{elapsed:.2f} ms`"
        if len(res) > 4000:
            res = res[:3900] + "\n... (truncated)```"
        await event.edit(res)
    except Exception as e:
        await event.edit(f"**Error:**\n`{e}`")
