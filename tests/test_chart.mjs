import test from 'node:test';
import assert from 'node:assert/strict';
import {ChartViewport, markerRadius, visibleSlice, drawSeries} from '../web/static/chart.mjs';

const MINUTE=60000, first=Date.parse('2026-09-29T00:00:00Z');
const configure=(view,extra={})=>view.update({session:'a',selection:'600',first,latest:first+120*MINUTE,...extra});

test('exact 30 minute threshold: shorter windows have small markers',()=>{
  assert.equal(markerRadius(5*MINUTE),1.2);
  assert.equal(markerRadius(30*MINUTE-1),1.2);
  assert.equal(markerRadius(30*MINUTE),0);
  assert.equal(markerRadius(120*MINUTE),0);
});

test('dragging right reveals older data, dragging left reveals newer data',()=>{
  const v=new ChartViewport(); configure(v);
  const latest=v.end;
  v.drag(latest,100,500);
  assert.equal(v.end,latest-2*MINUTE);
  assert.equal(v.following,false);
  v.drag(v.end,-50,500);
  assert.equal(v.end,latest-MINUTE);
});

test('panning clamps to both data boundaries and returns to follow at the newest edge',()=>{
  const v=new ChartViewport(); configure(v);
  v.panTo(first-1000);
  assert.equal(v.start,first); assert.equal(v.following,false);
  v.panTo(first+1000*MINUTE);
  assert.equal(v.end,first+120*MINUTE); assert.equal(v.following,true);
});

test('historical view remains fixed while new measurements arrive',()=>{
  const v=new ChartViewport(); configure(v); v.panTo(first+60*MINUTE);
  configure(v,{latest:first+121*MINUTE});
  assert.equal(v.end,first+60*MINUTE);
  v.follow(); assert.equal(v.end,first+121*MINUTE);
});

test('session or range changes reset follow; all and short sessions cannot pan',()=>{
  const v=new ChartViewport(); configure(v); v.panTo(first+60*MINUTE);
  configure(v,{selection:'1800'}); assert.equal(v.following,true);
  v.panTo(first+60*MINUTE);configure(v,{session:'b'});assert.equal(v.following,true);
  configure(v,{selection:'all'});assert.equal(v.canPan,false);assert.equal(v.start,first);
  configure(v,{latest:first+MINUTE});assert.equal(v.canPan,false);
});

test('binary window includes boundaries and duplicate timestamps, excludes unreplayed rows',()=>{
  const rows=[0,5000,5000,10000,20000].map(time_ms=>({time_ms}));
  assert.deepEqual(visibleSlice(rows,5,5000,10000).rows,rows.slice(1,4));
  assert.deepEqual(visibleSlice(rows,3,0,20000).rows,rows.slice(0,3));
  assert.equal(visibleSlice(rows,5,11000,19000).rows.length,0);
});

function canvasSpy(){
  const arcs=[],lines=[],moves=[];
  const ctx=new Proxy({arc:(...args)=>arcs.push(args),lineTo:(...args)=>lines.push(args),moveTo:(...args)=>moves.push(args)},
    {get:(obj,key)=>key in obj?obj[key]:()=>{}});
  return {arcs,lines,moves,canvas:{getBoundingClientRect:()=>({width:600,height:220}),getContext:()=>ctx}};
}

test('canvas actually omits dots for 30 minutes while preserving the trend line',()=>{
  const rows=[{time_ms:first,ds18:25},{time_ms:first+5000,ds18:26}];
  const long=canvasSpy();
  drawSeries(long.canvas,{key:'ds18',color:'#123',unit:'°C',rows,start:first,end:first+30*MINUTE});
  assert.equal(long.arcs.length,0);
  assert.ok(long.lines.length>4); // grid lines plus the measurement segment
  const short=canvasSpy();
  drawSeries(short.canvas,{key:'ds18',color:'#123',unit:'°C',rows,start:first,end:first+5*MINUTE});
  assert.equal(short.arcs.length,2);
  assert.ok(short.arcs.every(arc=>arc[2]===1.2));
});

test('line rendering preserves gaps and missing readings',()=>{
  const spy=canvasSpy();
  const rows=[{time_ms:first,ds18:25},{time_ms:first+5000,ds18:null},
    {time_ms:first+10000,ds18:26},{time_ms:first+30000,ds18:27}];
  drawSeries(spy.canvas,{key:'ds18',color:'#123',unit:'°C',rows,start:first,end:first+30*MINUTE});
  assert.equal(spy.lines.length,4); // only the four grid lines, no bridges over gaps
});
