/** Split by rendered capacity, keeping every character and grapheme intact. */
export function paginateText(text, fits) {
    if (!text) return [''];
    const segmenter = new Intl.Segmenter('pt-BR', { granularity: 'grapheme' });
    const characters = Array.from(segmenter.segment(text), item => item.segment);
    const pages = [];
    let offset = 0;
    while (offset < characters.length) {
        let low = 1, high = characters.length - offset, best = 0;
        while (low <= high) {
            const length = Math.floor((low + high) / 2);
            if (fits(characters.slice(offset, offset + length).join(''))) {
                best = length;
                low = length + 1;
            } else high = length - 1;
        }
        let end = offset + Math.max(1, best);
        if (end < characters.length) {
            const earliestBreak = offset + Math.floor(best * 0.75);
            for (let index = end - 1; index >= earliestBreak; index--) {
                if (/\s/u.test(characters[index])) { end = index + 1; break; }
            }
        }
        pages.push(characters.slice(offset, end).join(''));
        offset = end;
    }
    return pages;
}

export function pageForOffset(pages, offset) {
    let consumed = 0;
    for (let index = 0; index < pages.length; index++) {
        consumed += pages[index].length;
        if (offset < consumed) return index;
    }
    return Math.max(0, pages.length - 1);
}
