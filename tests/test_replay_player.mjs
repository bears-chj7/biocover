import test from 'node:test';
import assert from 'node:assert/strict';
import {Player} from '../replay/static/player.mjs';

const first = Date.parse('2026-09-29T00:00:00Z');
function recording(times=[0,5000,10000,15000]) {
  return {count:times.length, rows:times.map((t,i)=>({time_ms:first+t,ds18:i===1?null:20+i, mq1:100+i}))};
}
function setup(times) {
  let now = 0;
  const player = new Player(()=>now);
  player.load(recording(times));
  return {player, advance(ms) { now += ms; player.tick(); }};
}

test('original 5 second cadence, no future values or aggregation',()=>{
  const {player:p,advance} = setup();
  assert.equal(p.cursor,0);
  p.replay();
  assert.equal(p.cursor,1);
  assert.equal(p.stats.mq1.mean,100);
  advance(4999); assert.equal(p.cursor,1);
  advance(1); assert.equal(p.cursor,2);
  assert.equal(p.stats.mq1.mean,100.5);
  assert.equal(p.stats.ds18.count,1);
  assert.equal(p.latest.ds18,null);
});

test('pause freezes clock, resume does not count paused wall time',()=>{
  const {player:p,advance} = setup();
  p.replay(); advance(2500); p.pause(); advance(300000);
  assert.equal(p.position,2500); assert.equal(p.cursor,1);
  p.resume(); advance(2499); assert.equal(p.cursor,1);
  advance(1); assert.equal(p.cursor,2);
});

test('changing speed settles elapsed time at the previous speed',()=>{
  let now=0;
  const p=new Player(()=>now); p.load(recording()); p.replay();
  now=2000; p.setSpeed(50); // no tick since start
  assert.equal(p.position,2000);
  now=2060; p.tick(); assert.equal(p.position,5000); assert.equal(p.cursor,2);
  p.setSpeed(1); now=7060; p.tick(); assert.equal(p.cursor,3);
  assert.equal(p.stats.mq1.count,3);
});

test('50x catches up all rows, including a two hour measurement',()=>{
  const times=Array.from({length:1441},(_,i)=>i*5000);
  const {player:p,advance}=setup(times);
  p.setSpeed(50); p.replay(); advance(144000);
  assert.equal(p.state,'ended'); assert.equal(p.cursor,1441);
  assert.equal(p.stats.mq1.count,1441); assert.ok(Math.abs(p.stats.mq1.mean-820)<1e-9);
  assert.equal(p.recent().length,120);
  assert.equal(p.visible(300000).length,61);
  advance(10000); assert.equal(p.cursor,1441);
});

test('stop, replay, and selecting another file reset progress and statistics',()=>{
  const {player:p,advance}=setup(); p.replay(); advance(6000);
  p.stop(); assert.equal(p.state,'stopped'); assert.equal(p.cursor,0);
  assert.equal(p.latest,null); assert.equal(p.stats.ds18.mean,null);
  p.resume(); assert.equal(p.state,'stopped');
  p.replay(); assert.equal(p.cursor,1); assert.equal(p.stats.mq1.count,1);
  p.load(recording([0,1000])); assert.equal(p.state,'ready'); assert.equal(p.cursor,0);
});

test('duplicate timestamps, single row, and original pause gaps',()=>{
  const {player:p,advance}=setup([0,0,300000]);
  p.replay(); assert.equal(p.cursor,2); advance(299999); assert.equal(p.cursor,2);
  advance(1); assert.equal(p.state,'ended'); assert.equal(p.cursor,3);
  p.load(recording([0])); p.replay(); assert.equal(p.state,'ended'); assert.equal(p.cursor,1);
});

test('speed input rejects out of range, non-numbers, and fractions',()=>{
  const {player:p}=setup();
  for (const value of [0,51,-1,NaN,Infinity,'','oops',1.5]) assert.throws(()=>p.setSpeed(value));
  p.setSpeed('50'); assert.equal(p.speed,50);
  p.setSpeed(1); assert.equal(p.speed,1);
});

test('paused speed changes preserve position and resume at the new speed',()=>{
  const {player:p,advance}=setup(); p.replay(); advance(2000); p.pause();
  advance(100000); p.setSpeed(10); assert.equal(p.position,2000);
  p.resume(); advance(300); assert.equal(p.position,5000); assert.equal(p.cursor,2);
});

test('independent players never share session or speed',()=>{
  const a=setup(), b=setup(); a.player.setSpeed(50); a.player.replay(); a.advance(100);
  assert.equal(a.player.cursor,2); assert.equal(b.player.cursor,0); assert.equal(b.player.speed,1);
});

test('an earlier animation timestamp cannot move the anchor backwards',()=>{
  let now=0;
  const p=new Player(()=>now); p.load(recording()); p.replay();
  now=100; p.setSpeed(50);
  p.tick(90); p.tick(110);
  assert.equal(p.position,600);
});

test('seek backwards rebuilds statistics and logs without future values',()=>{
  const {player:p,advance}=setup(); p.replay(); advance(12000); p.pause();
  p.seek(6000);
  assert.equal(p.state,'paused'); assert.equal(p.cursor,2);
  assert.equal(p.stats.mq1.mean,100.5); assert.equal(p.stats.ds18.count,1);
  assert.equal(p.recent().length,2); assert.equal(p.visible(Infinity).length,2);
  p.seek(0); assert.equal(p.cursor,1); assert.equal(p.stats.mq1.mean,100);
});

test('seeking during playback continues from the target; ended can seek and resume',()=>{
  const {player:p,advance}=setup(); p.replay(); p.seek(9000); advance(1000);
  assert.equal(p.state,'running'); assert.equal(p.cursor,3);
  p.seek(999999); assert.equal(p.state,'ended'); assert.equal(p.cursor,4);
  p.seek(6000); assert.equal(p.state,'paused'); p.resume(); advance(4000);
  assert.equal(p.cursor,3); assert.equal(p.position,10000);
});

test('1 hour, 2 hour and whole-session windows include the intended records',()=>{
  const {player:p}=setup(Array.from({length:2000},(_,i)=>i*5000));
  p.seek(p.duration);
  assert.equal(p.visible(3600000).length,721);
  assert.equal(p.visible(7200000).length,1441);
  assert.equal(p.visible(Infinity).length,2000);
});

test('MQ #3/#4 aggregate separately, include legacy zeros and skip actual missing readings',()=>{
  const p=new Player(()=>0);
  p.load({rows:[
    {time_ms:0,mq3:0,mq4:0,mq34_backfilled:true},
    {time_ms:5000,mq3:714,mq4:526},
    {time_ms:10000,mq3:null,mq4:null}
  ]});
  p.seek(10000);
  assert.equal(p.stats.mq3.count,2);assert.equal(p.stats.mq3.mean,357);
  assert.equal(p.stats.mq4.count,2);assert.equal(p.stats.mq4.mean,263);
  p.seek(0);
  assert.equal(p.stats.mq3.mean,0);assert.equal(p.stats.mq4.mean,0);
});
