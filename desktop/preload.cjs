const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("jarvisDesktop", {
  startup: () => ipcRenderer.invoke("startup:get"),
  setStartup: (enabled) => ipcRenderer.invoke("startup:set", enabled),
  microphoneStatus: () => ipcRenderer.invoke("microphone:status"),
  fullscreen: () => ipcRenderer.invoke("fullscreen:get"),
  setFullscreen: (enabled) => ipcRenderer.invoke("fullscreen:set", enabled),
  onPause: (callback) => {
    const listener = () => callback();
    ipcRenderer.on("conversation:pause", listener);
    return () => ipcRenderer.removeListener("conversation:pause", listener);
  },
  onFullscreen: (callback) => {
    const listener = (_event, enabled) => callback(enabled === true);
    ipcRenderer.on("fullscreen:changed", listener);
    return () => ipcRenderer.removeListener("fullscreen:changed", listener);
  },
});
