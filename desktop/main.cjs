const {
  app,
  BrowserWindow,
  session,
  shell,
  ipcMain,
  systemPreferences,
  dialog,
  Menu,
} = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { authenticate } = require("./local-session.cjs");
let owned = null,
  window = null,
  quitting = false;
app.setName("Jarvis Local");
const root = path.resolve(__dirname, "..");
const origin = "http://127.0.0.1:8765";
if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => {
  window?.show();
  window?.focus();
});
const get = (pathname) =>
  new Promise((resolve, reject) => {
    const request = http.get(
      origin + pathname,
      { timeout: 2000 },
      (response) => {
        let body = "";
        response.on("data", (chunk) => (body += chunk));
        response.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on("error", reject);
    request.on("timeout", () => {
      request.destroy();
      reject(new Error("timeout"));
    });
  });
const local = (url) => {
  try {
    return new URL(url).origin === origin;
  } catch {
    return false;
  }
};
function trusted(event) {
  if (!local(event.senderFrame?.url || ""))
    throw new Error("Untrusted IPC sender");
}
ipcMain.handle("startup:get", (event) => {
  trusted(event);
  return {
    enabled: app.getLoginItemSettings().openAtLogin,
    supported: app.isPackaged,
  };
});
ipcMain.handle("startup:set", (event, enabled) => {
  trusted(event);
  if (typeof enabled !== "boolean" || !app.isPackaged)
    throw new Error("Login startup requires the installed desktop app");
  app.setLoginItemSettings({ openAtLogin: enabled, path: process.execPath });
  return app.getLoginItemSettings().openAtLogin;
});
ipcMain.handle("microphone:status", (event) => {
  trusted(event);
  return process.platform === "darwin"
    ? systemPreferences.getMediaAccessStatus("microphone")
    : "Use Windows microphone privacy settings";
});
ipcMain.handle("fullscreen:get", (event) => {
  trusted(event);
  return window?.isFullScreen() || false;
});
ipcMain.handle("fullscreen:set", (event, enabled) => {
  trusted(event);
  if (typeof enabled !== "boolean") throw new Error("Expected a boolean");
  window?.setFullScreen(enabled);
  return enabled;
});
app
  .whenReady()
  .then(async () => {
    app.setAccessibilitySupportEnabled(true);
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        { role: "appMenu" },
        {
          label: "Conversation",
          submenu: [
            {
              label: "Pause microphone and speech",
              accelerator: "CmdOrCtrl+Shift+.",
              click: () => window?.webContents.send("conversation:pause"),
            },
            { role: "quit" },
          ],
        },
        { role: "editMenu" },
        { role: "viewMenu" },
        { role: "windowMenu" },
      ]),
    );
    session.defaultSession.setPermissionCheckHandler(
      (_webContents, permission, requestingOrigin, details) =>
        permission === "media" &&
        local(requestingOrigin) &&
        details.mediaType !== "video",
    );
    session.defaultSession.setPermissionRequestHandler(
      async (contents, permission, callback, details) => {
        if (
          permission !== "media" ||
          !local(contents.getURL()) ||
          details.mediaTypes?.some((type) => type !== "audio")
        )
          return callback(false);
        if (process.platform === "darwin")
          return callback(
            await systemPreferences.askForMediaAccess("microphone"),
          );
        callback(true);
      },
    );
    const data = app.isPackaged
      ? app.getPath("userData")
      : path.join(root, "data");
    fs.mkdirSync(data, { recursive: true });
    let ready = false;
    try {
      ready = (await get("/api/ready")).ready === true;
    } catch {}
    if (!ready) {
      const command = app.isPackaged
        ? path.join(
            process.resourcesPath,
            "runtime",
            process.platform === "win32"
              ? "jarvis-runtime.exe"
              : "jarvis-runtime",
          )
        : path.join(root, ".venv", "bin", "python");
      const args = app.isPackaged
        ? ["--no-browser"]
        : [path.join(root, "scripts", "start.py"), "--no-browser"];
      const env = { ...process.env, JARVIS_DATA: data };
      if (app.isPackaged) {
        env.JARVIS_RESOURCES = process.resourcesPath;
        env.JARVIS_MODELS = path.join(data, "models");
        env.WHISPER_MODEL = path.join(data, "models", "ggml-small.bin");
      }
      owned = spawn(command, args, {
        cwd: app.isPackaged ? data : root,
        env,
        stdio: "ignore",
        windowsHide: true,
      });
      owned.on("error", (error) => {
        dialog.showErrorBox("Jarvis startup failed", error.message);
        app.quit();
      });
      for (let i = 0; i < 180; i++) {
        if (owned.exitCode !== null) break;
        try {
          if ((await get("/api/ready")).ready) {
            ready = true;
            break;
          }
        } catch {}
        await new Promise((r) => setTimeout(r, 500));
      }
    }
    if (!ready) {
      dialog.showErrorBox(
        "Jarvis is not ready",
        "Run setup and download the local engines and models. Check the backend logs in your Jarvis data folder.",
      );
      return app.quit();
    }
    let token;
    try {
      token = fs.readFileSync(path.join(data, "auth.token"), "utf8").trim();
    } catch {
      token = "";
    }
    if (!token) {
      dialog.showErrorBox(
        "Another Jarvis instance is using this port",
        "Close the other Jarvis instance, then reopen this app. Its private data folder differs from this installation.",
      );
      return app.quit();
    }
    window = new BrowserWindow({
      width: 1440,
      height: 940,
      minWidth: 420,
      minHeight: 650,
      backgroundColor: "#101815",
      title: "Jarvis Local",
      fullscreen: true,
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        webSecurity: true,
        autoplayPolicy: "no-user-gesture-required",
      },
    });
    window.webContents.on("before-input-event", (_event, input) => {
      if (input.type === "keyDown" && input.key === "Escape") {
        // Preserve the renderer's Escape handler for dialogs and focus restoration.
        window.webContents.send("conversation:pause");
      }
    });
    window.on("enter-full-screen", () =>
      window.webContents.send("fullscreen:changed", true),
    );
    window.on("leave-full-screen", () =>
      window.webContents.send("fullscreen:changed", false),
    );
    window.webContents.setWindowOpenHandler(({ url }) => {
      try {
        const target = new URL(url);
        if (
          target.protocol === "https:" &&
          [
            "accounts.google.com",
            "maps.apple.com",
            "www.google.com",
            "vertexaisearch.cloud.google.com",
            "www.bbc.com",
            "www.bbc.co.uk",
            "www.theguardian.com",
            "indianexpress.com",
            "www.indianexpress.com",
          ].includes(target.hostname)
          || (target.protocol === "https:" && target.hostname === "github.com" && target.pathname.startsWith("/rythmscape11/jarvis-local-community/releases"))
        )
          shell.openExternal(url);
        else if (target.protocol === "https:" && !target.username && !target.password && !["localhost", "127.0.0.1", "::1"].includes(target.hostname)) {
          dialog.showMessageBox(window, {type:"question",buttons:["Cancel","Open source"],defaultId:0,cancelId:0,title:"Open retrieved source",message:"Open this source in your browser?",detail:target.href}).then(({response}) => {if(response === 1) shell.openExternal(target.href);});
        }
      } catch {}
      return { action: "deny" };
    });
    window.webContents.on("will-navigate", (event, url) => {
      if (!local(url)) event.preventDefault();
    });
    const sessionToken = await authenticate(token, origin);
    await session.defaultSession.cookies.set({url:origin,name:"jarvis_session",value:sessionToken,httpOnly:true,sameSite:"strict",path:"/",expirationDate:Date.now()/1000 + 12*3600});
    window.loadURL(origin);
    app.on("activate", () => {
      window?.show();
    });
  })
  .catch((error) => {
    dialog.showErrorBox("Jarvis Local", error.message);
    app.quit();
  });
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (owned && !quitting && owned.exitCode === null) {
    event.preventDefault();
    quitting = true;
    owned.kill("SIGTERM");
    const timer = setTimeout(() => {
      owned.kill("SIGKILL");
      app.quit();
    }, 12000);
    owned.once("exit", () => {
      clearTimeout(timer);
      app.quit();
    });
  }
});
