import fs from 'node:fs/promises';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';
import { finalizePresentation } from 'file:///C:/Users/playdata2/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools/artifact_tool_utils.mjs';

const base='C:/project_workspace/TrueFit/docs/db';
const build=base+'/.pptx-build';
const skill='C:/Users/playdata2/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const svg=await fs.readFile(base+'/database-structure-overview.svg','utf8');
const p=Presentation.create({slideSize:{width:3360,height:1160}});
const s=p.slides.add(); s.background.fill='#f8fafc';
let textCount=0;
const attrs=str=>Object.fromEntries([...str.matchAll(/([\w-]+)="([^"]*)"/g)].map(m=>[m[1],m[2]]));
for(const m of svg.matchAll(/<(rect|polyline|text)\b([^>]*?)(?:\/>|>(.*?)<\/text>)/gs)) {
  const a=attrs(m[2]);
  if(m[1]==='rect') {
    if(!a.x)continue;
    s.shapes.add({name:'영역 상자',geometry:'roundRect',position:{left:+a.x,top:+a.y,width:+a.width,height:+a.height},fill:a.fill,line:{fill:a.stroke??'none',width:2}});
  } else if(m[1]==='polyline') {
    const pts=a.points.split(' ').map(v=>v.split(',').map(Number));
    for(let i=1;i<pts.length;i++) {
      const [x,y]=pts[i-1], [xx,yy]=pts[i];
      s.shapes.add({name:'소속 관계 연결선',geometry:'line',position:{left:x,top:y,width:xx-x,height:yy-y},fill:'none',line:{fill:a.stroke,width:+a['stroke-width'],style:a['stroke-dasharray']?'dash':'solid'}});
    }
  } else {
    const value=m[3].replaceAll('&amp;','&').replaceAll('&lt;','<').replaceAll('&gt;','>');
    const size=+a['font-size'], x=+a.x, top=+a.y-size;
    const centered=a['text-anchor']==='middle';
    const width=centered?(top>380&&top<500?246:(x===1680?790:x===2880?810:385)):
      (top>=570&&top<970?220:Math.min(3100-x,Math.max(250,[...value].reduce((v,c)=>v+(c.charCodeAt(0)>255?1.02:0.66)*size,0)+30)));
    const shape=s.shapes.add({name:value,geometry:'textbox',position:{left:centered?x-width/2:x,top,width,height:size*1.55},fill:'none',line:{fill:'none',width:0}});
    shape.text=value;
    shape.text.style={typeface:'Malgun Gothic',fontSize:size,bold:a['font-weight']==='700',color:a.fill,alignment:centered?'center':'left',verticalAlignment:'top',autoFit:'none',wrap:'none',insets:{left:0,right:0,top:0,bottom:0}};
    textCount++;
  }
}
s.speakerNotes.textFrame.setText('출처: docs/db/table_spec.md, 테이블 명세서 v4 (2026-09-10). 12개 스키마와 58개 테이블. 연결선은 소속 관계이며 FK를 표시하지 않는다.');
await fs.mkdir(base+'/pptx',{recursive:true});
const candidate=build+'/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
console.log('Draft exported; editable text boxes:',textCount);
await finalizePresentation({workspaceDir:base,candidatePath:candidate,finalPath:base+'/pptx/database-structure-overview.pptx',pythonExecutable:'C:/Users/playdata2/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','32004000,11049000','--validate-heading-fit'],explicitTotalSlideCount:1,fontPolicy:{basis:'design',families:['Malgun Gothic']},verifyArtifactToolImport:true,receiptPath:build+'/validation.json'});
const final=await PresentationFile.importPptx(await FileBlob.load(base+'/pptx/database-structure-overview.pptx'));
const preview=await final.export({slide:final.slides.items[0],format:'png',scale:0.65});
await fs.writeFile(build+'/preview.png',new Uint8Array(await preview.arrayBuffer()));
console.log('Final PPTX and preview saved.');


