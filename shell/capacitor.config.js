// The shell loads the PWA from the backend, so a change to the screens needs no rebuild of the app.
// The backend's address is personal, so it comes from the environment instead of this file.
//
//   CPC_SHELL_SERVER_URL      the backend as the phone reaches it (e.g. https://<host>.<tailnet>.ts.net)
const serverUrl = process.env.CPC_SHELL_SERVER_URL;

module.exports = {
  appId: 'com.local.claudepwaclient',
  appName: 'Claude PWA',
  webDir: 'www',
  ...(serverUrl ? { server: { url: serverUrl } } : {}),
};
