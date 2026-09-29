import test from 'node:test';
import assert from 'node:assert/strict';
import {LiveHistory} from '../web/static/history.mjs';

test('backfills older rows beyond 720 and merges ongoing samples without duplicates',async()=>{
  const rows=Array.from({length:1951},(_,i)=>({sequence:i+1}));
  const h=new LiveHistory(async after=>({session:'a',rows:rows.slice(after,after+500),through:Math.min(after+500,rows.length)}));
  h.ingest({started_at:'a',count:1951,rows:rows.slice(-720)});
  await h.fill();
  assert.equal(h.rows.length,1951); assert.equal(h.through,1951);
  assert.equal(h.rows[0].sequence,1); assert.equal(h.rows.at(-1).sequence,1951);
  h.ingest({started_at:'a',count:1952,rows:[{sequence:1951},{sequence:1952}]});
  assert.equal(h.rows.length,1952); assert.equal(h.through,1952);
});

test('late response for an old session cannot overwrite the new session',async()=>{
  let resolve;
  const h=new LiveHistory(()=>new Promise(r=>resolve=r));
  h.ingest({started_at:'a',count:1000,rows:[{sequence:1000}]});
  const filling=h.fill();
  h.ingest({started_at:'b',count:1,rows:[{sequence:1}]});
  resolve({session:'a',through:1000,rows:[{sequence:999}]});
  await filling;
  assert.equal(h.session,'b'); assert.equal(h.rows.length,1); assert.equal(h.loading,false);
});

test('failed backfill preserves recent data and can retry',async()=>{
  const h=new LiveHistory(async()=>{throw Error('offline')});
  h.ingest({started_at:'a',count:1000,rows:[{sequence:1000}]});
  await h.fill(); assert.equal(h.rows.length,1); assert.ok(h.message);
  h.fetchPage=async()=>({session:'a',through:1000,rows:[{sequence:1}]});
  await h.fill(); assert.equal(h.message,''); assert.equal(h.rows.length,2);
});
