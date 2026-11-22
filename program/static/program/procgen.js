(() => {
    const form = document.getElementById('proceedings-upload');
    if (!form) return;
    const input = form.querySelector('input[type="file"]');
    const zone = document.getElementById('pdf-drop-zone');
    const summary = document.getElementById('selected-files');
    const button = form.querySelector('button[type="submit"]');
    const showSelection = () => {
        const files = Array.from(input.files);
        summary.textContent = files.length
            ? `${files.length}件選択: ${files.map(file => file.name).join('、')}`
            : 'ファイルが選択されていません。';
    };
    input.addEventListener('change', showSelection);
    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => {
        event.preventDefault();
        zone.classList.add('drag-over');
    }));
    zone.addEventListener('dragleave', event => {
        if (!zone.contains(event.relatedTarget)) zone.classList.remove('drag-over');
    });
    zone.addEventListener('drop', event => {
        event.preventDefault();
        zone.classList.remove('drag-over');
        if (!event.dataTransfer.files.length) return;
        input.files = event.dataTransfer.files;
        showSelection();
    });
    form.addEventListener('submit', () => {
        button.disabled = true;
        button.textContent = 'アップロード中…';
    });
    window.addEventListener('pageshow', () => {
        button.disabled = false;
        button.textContent = 'アップロード';
        showSelection();
    });
})();


[
    ['proceedings-settings', 'proceedings-build'],
    ['metadata-settings', 'proceedings-metadata'],
].forEach(([dialogId, formId]) => {
    const dialog = document.getElementById(dialogId);
    if (!dialog) return;
    const form = document.getElementById(formId);
    const open = () => {
        if (!dialog.open) dialog.showModal();
    };
    document.getElementById(dialogId + '-open').addEventListener('click', open);
    document.getElementById(dialogId + '-close').addEventListener('click', () => dialog.close());
    document.getElementById(dialogId + '-apply').addEventListener('click', () => {
        if (form.reportValidity()) dialog.close();
    });
    // Open hidden invalid fields before the browser tries to focus them.
    form.addEventListener('invalid', open, true);
    // Enter in a setting field applies settings without submitting the form.
    dialog.addEventListener('keydown', event => {
        if (event.key === 'Enter' && event.target.matches('input')) {
            event.preventDefault();
            if (form.reportValidity()) dialog.close();
        }
    });
    if (dialog.dataset.hasErrors === 'true') open();
});
