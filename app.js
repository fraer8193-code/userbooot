const { spawn } = require("child_process");

console.log("==================================================");
console.log("🚀 [Bothost] Node.js bridge activated! Starting Python Userbot...");
console.log("==================================================");

const pythonCmd = process.platform === "win32" ? "python" : "python3";
const bot = spawn(pythonCmd, ["main.py"], { cwd: __dirname, stdio: "inherit" });

bot.on("error", (err) => {
  console.warn("Could not start python3, falling back to python:", err.message);
  const fallback = spawn("python", ["main.py"], { cwd: __dirname, stdio: "inherit" });
  fallback.on("exit", (code) => process.exit(code || 0));
});

bot.on("exit", (code) => {
  process.exit(code || 0);
});
