import test from 'node:test';
import assert from 'node:assert/strict';
import { cropRectangle } from '../static/forms/crop-geometry.mjs';

test('square avatar is centered and contains only original pixels', () => {
    assert.deepEqual(cropRectangle(1200, 800, 1), {x:200,y:0,width:800,height:800});
});
test('cover maintains its aspect ratio at every zoom and position', () => {
    for (const [width,height] of [[400,1000],[2000,300],[1,1]]) {
        for (const zoom of [1,1.5,3]) for (const pos of [0,.5,1]) {
            const crop = cropRectangle(width,height,1.5625,zoom,pos,1-pos);
            assert.ok(Math.abs(crop.width/crop.height-1.5625) < 1e-9);
            assert.ok(crop.x >= 0 && crop.y >= 0 && crop.x+crop.width <= width+1e-9 && crop.y+crop.height <= height+1e-9);
        }
    }
});
test('invalid dimensions fail and position/zoom stay within usable limits', () => {
    assert.throws(() => cropRectangle(0,100,1), RangeError);
    assert.deepEqual(cropRectangle(400,200,1,0,-1,2), {x:0,y:0,width:200,height:200});
});
