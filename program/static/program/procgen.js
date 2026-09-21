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
