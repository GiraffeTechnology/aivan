# Local inquiry image preview: unapplied host wiring

This module is source development only. It is not loaded by the current page,
not a saved attachment workflow, and not tested or accepted. Existing case
attachment upload and verified server-image preview remain unchanged.

## Required integration delta for the current UI owner

The following changes have NOT been applied to the handed-off template or app:

1. Add an empty `div` with ID `inquiry-local-image` inside the initial inquiry
   form. Keep the existing TXT controls and persisted-case attachment UI.
2. Statically load `/static/local-image-input.js` with `defer` before `app.js`,
   alongside the existing scripts. Do not dynamically discover scripts or load
   a remote module.
3. On authenticated entry to the new-inquiry view, explicitly mount with
   `window.myAivanLocalImageInput.mount(root)` and retain the returned handle.
   Dispose the previous handle before remounting; do not mount on every input.
4. Call the handle's `dispose()` and clear the handle on view departure,
   logout/session expiry and actor/tenant change. Call `clear()` when starting
   a distinct inquiry or resetting the form. Invalidate the preview immediately,
   not after logout HTTP finishes. Login failure paths must also dispose it.
5. A failed inquiry submission must not display a saved-file claim. The image
   is never included in `/invoke`; relevant text is explicitly entered and
   reviewed by the user. Actual attachment saving uses the existing authorized
   case attachment controls after the necessary provider case exists.

No UI wiring is complete until these lifecycle points are integrated and
verified. Merely including the script does not make the feature operational.

## Module behavior and receiver checks

The control accepts nonempty PNG/JPEG up to 10 MiB, checks MIME and file header,
and relies on browser image decoding for preview. This is not malware scanning,
OCR or server-side upload validation. Filename is displayed with textContent.
The module makes no requests, stores no business state and never submits a form.
The clear button has type=button. Replacing, clearing or disposing a selection
invalidates pending reads/decodes and revokes the object URL. The host owns the
mandatory lifecycle integration described above.

Receiving owner should check valid PNG/JPEG, mismatched or malformed content,
empty/oversized files, image decode errors, filename markup, selection races,
clear during read/decode, view/actor/logout cleanup, object URL release and zero
network/form submissions. None of these tests has been run by the developer.

This supports only the local selection/preview part of Web PRD section3 image
input. Durable upload/readback, attachment-driven understanding, full workflow
and real MySQL/public deployment remain unproven. No image facts are fabricated.
