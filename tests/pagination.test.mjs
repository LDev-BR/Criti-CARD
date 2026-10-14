import test from 'node:test';
import assert from 'node:assert/strict';
import { paginateText, pageForOffset } from '../static/reading/pagination.mjs';

test('short reviews fit on one page', () => {
    assert.deepEqual(paginateText('Muito boa', text => text.length <= 30), ['Muito boa']);
});

test('long reviews preserve every character and respect available space', () => {
    const text = 'Muito boaMuito boa'.repeat(180);
    const pages = paginateText(text, candidate => candidate.length <= 130);
    assert.ok(pages.length > 1);
    assert.equal(pages.join(''), text);
    assert.ok(pages.every(page => page.length <= 130));
});

test('long words, newlines and empty input cannot lose text or stall', () => {
    for (const text of ['x'.repeat(1000), 'Primeiro\n\nSegundo\nTerceiro', '']) {
        const pages = paginateText(text, candidate => candidate.length <= 7);
        assert.equal(pages.join(''), text);
        assert.ok(pages.length >= 1);
        assert.ok(pages.every(page => page.length <= 7));
    }
});

test('Unicode emoji and combining characters stay intact', () => {
    const text = 'Família 👨‍👩‍👧‍👦 e café cafe\u0301 ❤️ '.repeat(20);
    const segmenter = new Intl.Segmenter('pt-BR', { granularity: 'grapheme' });
    const pages = paginateText(text, candidate => [...segmenter.segment(candidate)].length <= 8);
    assert.equal(pages.join(''), text);
    for (const page of pages) {
        assert.ok([...segmenter.segment(page)].length <= 8);
        assert.ok(!page.startsWith('\u200d') && !page.endsWith('\u200d'));
    }
});

test('an extremely small viewport still makes progress', () => {
    assert.deepEqual(paginateText('abc', () => false), ['a', 'b', 'c']);
});

test('resizing preserves the page containing the current text position', () => {
    assert.equal(pageForOffset(['abc', 'def', 'ghi'], 0), 0);
    assert.equal(pageForOffset(['abc', 'def', 'ghi'], 3), 1);
    assert.equal(pageForOffset(['abc', 'def', 'ghi'], 8), 2);
    assert.equal(pageForOffset(['abc', 'def', 'ghi'], 99), 2);
});
