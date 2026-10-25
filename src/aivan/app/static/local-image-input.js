'use strict';

// Explicitly mounted by the host. No network, OCR, persistence or form submission.
window.myAivanLocalImageInput = (() => {
  const maxBytes = 10 * 1024 * 1024;

  function mount(root) {
    let disposed = false;
    let generation = 0;
    let objectUrl = null;
    let pendingImage = null;
    const node = (tag, text) => {
      const element = document.createElement(tag);
      if (text) element.textContent = text;
      return element;
    };
    const label = node('label', 'Choose a PNG or JPEG for local preview (maximum 10 MiB)');
    const input = node('input');
    input.type = 'file';
    input.accept = '.png,.jpg,.jpeg,image/png,image/jpeg';
    label.append(input);
    const remove = node('button', 'Clear local image');
    remove.type = 'button';
    const status = node('p', 'Local preview only. No upload, saved attachment, OCR or extracted business facts.');
    status.setAttribute('role', 'status');
    const preview = node('div');
    root.replaceChildren(label, remove, status, preview);

    function clear() {
      generation += 1;
      if (pendingImage) {
        pendingImage.onload = null;
        pendingImage.onerror = null;
        pendingImage.removeAttribute('src');
        pendingImage = null;
      }
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      input.value = '';
      preview.replaceChildren();
      status.textContent = 'Local image cleared. No file was uploaded or saved.';
    }

    const onChange = async () => {
      const file = input.files?.[0];
      clear();
      if (!file || disposed) return;
      const selectedGeneration = generation;
      const current = () => !disposed && root.isConnected && generation === selectedGeneration;
      if (!['image/png', 'image/jpeg'].includes(file.type) || file.size < 1 || file.size > maxBytes) {
        status.textContent = 'Choose a non-empty PNG or JPEG up to 10 MiB. Nothing was uploaded.';
        return;
      }
      status.textContent = 'Reading a local preview. Nothing is being submitted.';
      try {
        const header = new Uint8Array(await file.slice(0, 8).arrayBuffer());
        if (!current()) return;
        const png = [137, 80, 78, 71, 13, 10, 26, 10];
        const valid = file.type === 'image/png'
          ? header.length === 8 && png.every((value, index) => header[index] === value)
          : header.length >= 3 && header[0] === 255 && header[1] === 216 && header[2] === 255;
        if (!valid) throw Error('INVALID_IMAGE');
        const image = node('img');
        image.alt = 'Local image preview; not uploaded or parsed';
        image.className = 'attachment-preview';
        pendingImage = image;
        objectUrl = URL.createObjectURL(file);
        image.onload = () => {
          if (!current()) return;
          if (!image.naturalWidth || !image.naturalHeight) {
            clear();
            status.textContent = 'Image preview unavailable. No upload or extracted content is claimed.';
            return;
          }
          preview.replaceChildren(node('p', file.name), image);
          status.textContent = 'Local preview only, not uploaded or saved. Describe the relevant details in your input; no OCR has been performed.';
        };
        image.onerror = () => {
          if (!current()) return;
          clear();
          status.textContent = 'Image preview unavailable. No upload or extracted content is claimed.';
        };
        image.src = objectUrl;
      } catch {
        if (!current()) return;
        clear();
        status.textContent = 'Cannot preview this image. Choose a valid PNG or JPEG; nothing was uploaded.';
      }
    };
    input.addEventListener('change', onChange);
    remove.addEventListener('click', clear);
    return {
      clear,
      dispose() {
        disposed = true;
        clear();
        input.removeEventListener('change', onChange);
        remove.removeEventListener('click', clear);
        root.replaceChildren();
      },
    };
  }

  return {mount};
})();
