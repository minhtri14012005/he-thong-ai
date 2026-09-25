// Logic checks with a minimal DOM; does not substitute visual browser QA.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

export async function runVideoUiTests(root) {
    const elements = new Map();
    class Element {
        constructor() { this.children=[]; this.style={}; this.value=''; this.checked=false; this.textContent=''; this.classList={add(){},remove(){},toggle(){}}; }
        set id(value) { this._id=value; elements.set(value,this); }
        get id() { return this._id; }
        append(...values) { this.children.push(...values); }
        appendChild(value) { this.append(value); }
        insertBefore(value, next) {
            const index = next == null ? -1 : this.children.indexOf(next);
            this.children.splice(index < 0 ? this.children.length : index, 0, value);
        }
        replaceChildren(...values) { this.children=values; }
        load() {}
        play() { return Promise.resolve(); }
        remove() {}
    }
    const document = {
        getElementById(id) { if (!elements.has(id)) elements.set(id,new Element()); return elements.get(id); },
        createElement() { return new Element(); }, querySelectorAll() { return []; }
    };
    const toasts=[], timers=[];
    const context = vm.createContext({document, window:{}, console, FormData:class {append(){}},
        currentJobId:'job', lastDetectionId:0, pollInterval:null, isVideoPlayerVisible:true,
        showToast:(message)=>toasts.push(message), setTimeout:(fn)=>{timers.push(fn);return timers.length;}, clearTimeout(){}});
    const source = await readFile(root+'/static/js/analysis.js','utf8');
    new vm.Script(source,{filename:'analysis.js'}).runInContext(context);
    const event = {id:1,person_id:1,person_name:'A<script>',confidence:.8,timestamp_sec:.5,
        timestamp_str:'00:00.500',snapshot_path:'/static/snapshots/face.jpg',scene_path:'/static/snapshots/scene.jpg',zone:'Door'};
    context.batch=[event,event];
    vm.runInContext('handleNewDetections(batch)',context);
    assert.equal(toasts.length,1,'retried events must not alert twice');
    assert.equal(document.getElementById('totalPeopleBadge').textContent,'1 người');
    assert.equal(document.getElementById('detectedCountBadge').textContent,'1 lượt xuất hiện');
    assert.equal(document.getElementById('videoAlertBanner').textContent,'Đã xác nhận A<script> tại 00:00.500 · Door');
    const card=document.getElementById('personGalleriesContainer').children[0];
    assert.equal(card.children[0].children[0].textContent,'A<script>','names use textContent');
    assert.equal(card.children[1].children[0].children[1].children.at(-1).href,event.scene_path);
    const imageWrapper = card.children[1].children[0].children[0];
    const imageButton = imageWrapper.children[0];
    const image = imageButton.children[0];
    assert.equal(image.loading,'eager','new result thumbnails must load immediately');
    assert.equal(image.src,event.snapshot_path);
    assert.equal(imageWrapper.className,'moment-img-wrapper');
    imageButton.onclick();
    assert.equal(document.getElementById('photoModalImg').src,event.snapshot_path);
    image.onerror();
    assert.equal(imageButton.hidden,true);
    assert.equal(imageWrapper.children[1].hidden,false);
    imageWrapper.children[1].children[1].onclick();
    assert.match(image.src,/retry=/);
    image.onload();
    assert.equal(imageWrapper.children[1].hidden,true);
    card.children[1].children[0].children[1].children[0].onclick();
    assert.equal(document.getElementById('html5VideoPlayer').currentTime,0.5);
    context.batch=[{...event,id:2,timestamp_sec:8,timestamp_str:'00:08.000'}];
    vm.runInContext('handleNewDetections(batch)',context);
    assert.equal(toasts.length,2,'new appearance alerts again');
    vm.runInContext("applyAppearanceUpdates([{id:2,last_seen_sec:9.25,last_zone:'Desks'}])",context);
    assert.match(document.getElementById('video-last-2').textContent,/00:09.250.*Desks/);
    const sample = {...event, id:10, detection_id:1, timestamp_sec:2.5, timestamp_str:'00:02.500',
        snapshot_path:'static/snapshots/extra.jpg', scene_path:'static/snapshots/extra-scene.jpg', kind:'interval'};
    const finalSample = {...sample, id:11, timestamp_sec:3.75, timestamp_str:'00:03.750', kind:'last'};
    context.samples = [sample, finalSample, sample];
    vm.runInContext('handleVideoSnapshots(samples)',context);
    assert.equal(toasts.length,2,'extra photos do not trigger appearance notifications');
    assert.equal(document.getElementById('detectedCountBadge').textContent,'2 lượt xuất hiện');
    assert.equal(card.children[0].children[1].textContent,'2 lượt · 4 ảnh');
    assert.deepEqual(card.children[1].children.map(c => c.children[1].children[0].textContent),
        ['00:00.500','00:02.500','00:03.750','00:08.000'],'photos stay chronological even when appearances arrive first');
    assert.equal(card.children[1].children[2].children[1].children[3].textContent,'Lượt 1 · Ảnh cuối');
    card.children[1].children[1].children[1].children[0].onclick();
    assert.equal(document.getElementById('html5VideoPlayer').currentTime,2.5);
    card.children[1].children[1].children[0].children[0].onclick();
    assert.equal(document.getElementById('photoModalImg').src,'/static/snapshots/extra.jpg');
    assert.equal(vm.runInContext("videoSnapshotPath('https://example.com/image.jpg')",context),'');
    for (const input of ['static/snapshots/a.jpg','/static/snapshots/a.jpg','//static/snapshots/a.jpg']) {
        context.testPath=input;
        assert.equal(vm.runInContext('videoSnapshotPath(testPath)',context),'/static/snapshots/a.jpg');
    }
    context.fetch=async()=>({ok:true,status:200,json:async()=>({status:'processing',progress:50,last_id:2,
        new_detections:[],new_snapshots:[sample],last_snapshot_id:11,appearance_updates:[],scanned_until_sec:10,scanned_frames:20})});
    await vm.runInContext('pollVideoEvents()',context);
    assert.equal(timers.length,1,'one next poll, not overlapping intervals');
    assert.equal(context.lastDetectionId,2);
    assert.equal(vm.runInContext('lastVideoSnapshotId',context),11);
    assert.equal(card.children[1].children.length,4,'poll retries do not duplicate photos');
    context.fetch=async()=>({ok:true,status:200,json:async()=>({status:'error',progress:50,last_id:2,
        new_detections:[],error_message:'Damaged file'})});
    await vm.runInContext('pollVideoEvents()',context);
    assert.match(document.getElementById('videoProgressText').textContent,/Damaged file/);
    assert.equal(timers.length,1,'terminal job stops polling');
    assert.equal(document.getElementById('analyzeBtn').disabled,false);
    // A response from an old job must not alter the current job.
    context.fetch=async()=>{context.currentJobId='newjob';return {ok:true,status:200,json:async()=>({status:'completed',progress:100})};};
    const before=document.getElementById('videoProgressText').textContent;
    await vm.runInContext('pollVideoEvents()',context);
    assert.equal(document.getElementById('videoProgressText').textContent,before);
    return 'Video UI tests passed: deduplication, alerts, evidence, seek metadata, errors, polling and stale responses.';
}
