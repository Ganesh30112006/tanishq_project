/**
 * "Upload a report" can be pressed from anywhere - the sidebar, the mobile tab
 * bar, the command palette, the overview. The reports page owns the upload
 * area, so the request is a flag it reads when it mounts, plus an event for
 * when it is already on screen.
 */
const EVENT = 'caresense:upload-requested';
let pending = false;

export function requestUpload(): void {
  pending = true;
  window.dispatchEvent(new Event(EVENT));
}

/** True once, if an upload was requested before the reports page mounted. */
export function consumeUploadRequest(): boolean {
  const was = pending;
  pending = false;
  return was;
}

export function onUploadRequested(handler: () => void): () => void {
  const listener = () => { pending = false; handler(); };
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
