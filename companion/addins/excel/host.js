/* ExcelApi 1.13. Track cell objects; one explicitly typed write per checkpoint. */
window.KotoExcelHost=({safe,makeTarget,observation,samePath})=>{
  let target=null,bound={};const fileInfo=KotoOfficeFile();
  const raw=cell=>typeof cell.formulas[0][0]==='string'&&cell.formulas[0][0].startsWith('=')?cell.formulas[0][0]:String(cell.values[0][0]??'');
  const fingerprint=cell=>JSON.stringify([typeof cell.formulas[0][0]==='string'&&cell.formulas[0][0].startsWith('=')?null:cell.values,cell.formulas,cell.valueTypes,cell.numberFormat,cell.address]);
  function load(cell){cell.load('address,values,formulas,valueTypes,numberFormat,hasSpill');cell.worksheet.load('id,name');cell.worksheet.protection.load('protected');return cell.getMergedAreasOrNullObject();}
  function writable(cell,merged){return Office.context.document.mode!=='readOnly'&&!cell.worksheet.protection.protected&&merged.isNullObject&&cell.hasSpill===false&&['String','Double','Boolean','Empty','Integer'].includes(cell.valueTypes[0][0]);}
  async function release(items){const cells=Object.values(items).map(item=>item.cell);if(cells.length)try{await Excel.run(cells,async ctx=>{for(const cell of cells)ctx.trackedObjects.remove(cell);await ctx.sync();});}catch(_){} }
  function check(id,fragment){if(!target||target.id!==id||fragment&&!bound[fragment])throw safe('单元格绑定已失效，请重新选择。','conflict');return fragment?bound[fragment]:Object.values(bound)[0];}
  async function verify(entry,expected){
    const merged=load(entry.cell);await entry.cell.context.sync();
    if(fingerprint(entry.cell)!==entry.version||raw(entry.cell)!==expected)throw safe('单元格内容、位置或格式已变化，请重新读取。','conflict');
    if(!writable(entry.cell,merged))throw safe('保护、合并、溢出或特殊数据单元格暂不写入。','conflict');
  }
  async function fullSnapshot(){
    const n=await fileInfo();return Excel.run(async ctx=>{
      const sheets=ctx.workbook.worksheets;sheets.load('items/id,items/name');await ctx.sync();
      const parts=[],limits=['图表、图片、批注及数据模型未解析'];let count=0;const coverage=[];
      for(const sheet of sheets.items){
        const used=sheet.getUsedRangeOrNullObject();used.load('rowCount,columnCount');await ctx.sync();if(used.isNullObject)continue;
        if(used.rowCount*used.columnCount>20000||count+used.rowCount*used.columnCount>40000){limits.push(sheet.name+'范围超过读取上限，未读取');continue;}
        used.load('values,formulas,address');await ctx.sync();count+=used.rowCount*used.columnCount;coverage.push(sheet.name);
        parts.push('['+sheet.name+' · '+used.address+']');
        for(let r=0;r<used.rowCount;r++){const row=[];for(let c=0;c<used.columnCount;c++){const f=used.formulas[r][c],v=used.values[r][c];row.push(typeof f==='string'&&f.startsWith('=')?f+' [当前结果:'+v+']':String(v??''));}parts.push(row.join('\t'));}
      }
      return {name:n.name,text:parts.join('\n'),coverage,limitations:limits};
    });
  }
  return {
    async observe(){
      const n=await fileInfo();return Excel.run(async ctx=>{
        const range=ctx.workbook.getSelectedRange();range.load('address,rowCount,columnCount');await ctx.sync();
        const count=range.rowCount*range.columnCount;let text='';
        if(count<=200){range.load('text');await ctx.sync();text=range.text.map(row=>row.join('\t')).join('\n');}
        const value=observation(n.name,n.path,text,true,null);
        return {...value,location:range.address,unit:'单元格',selection:{active:true,count,address:range.address},selection_summary:range.address+' · '+count+' 个单元格',context_truncated:count>200,tables_pending:false};
      });
    },
    async bind(){
      const next={};let committed=false;
      try{
        const fragments=await Excel.run(async ctx=>{
          const selection=ctx.workbook.getSelectedRange();selection.load('rowCount,columnCount');await ctx.sync();
          if(selection.rowCount*selection.columnCount>50)throw safe('请一次选择不超过50个单元格。');
          const prepared=[];
          for(let r=0;r<selection.rowCount;r++)for(let c=0;c<selection.columnCount;c++){
            const cell=selection.getCell(r,c),id='c'+prepared.length;ctx.trackedObjects.add(cell);const merged=load(cell);next[id]={cell};prepared.push({id,cell,merged});
          }
          await ctx.sync();
          return prepared.map(({id,cell,merged})=>{
            next[id].version=fingerprint(cell);const editable=writable(cell,merged),text=raw(cell);
            if(text.length>8000)throw safe('单元格内容过长，请缩小范围。');
            return {id,text,label:cell.address,kind:'cell',metadata:{value_type:typeof cell.formulas[0][0]==='string'&&cell.formulas[0][0].startsWith('=')?'formula':typeof cell.values[0][0],display:cell.values[0][0],number_format:cell.numberFormat[0][0]},editable,reason:editable?'':'保护、合并、溢出或特殊数据单元格可读取，暂不修改。'};
          });
        });
        const n=await fileInfo(true),previous=bound;bound=next;target={...makeTarget(crypto.randomUUID(),n.name,n.path,fragments,true),scope:'已选单元格'};committed=true;await release(previous);return target;
      }finally{if(!committed)await release(next);}
    },
    async read(id,fragment){const item=check(id,fragment);return Excel.run(item.cell,async ctx=>{item.cell.load('values,formulas');await ctx.sync();return raw(item.cell);});},
    async context(id){check(id);const cells=Object.values(bound).map(item=>item.cell);return Excel.run(cells,async ctx=>{
      for(const cell of cells)cell.load('values,formulas,address');await ctx.sync();return {selection:{active:true,text:cells.map(cell=>cell.address+'\t'+raw(cell)).join('\n')},cells:cells.map(cell=>({address:cell.address,value:cell.values[0][0],formula:cell.formulas[0][0]}))};
    });},
    async replace_cell(id,fragment,expected,type,value,permit){
      const entry=check(id,fragment);return Excel.run(entry.cell,async ctx=>{
        await verify(entry,expected);if(!await permit())throw safe('已停止，未写入单元格。');await verify(entry,expected);
        try{
          if(type==='formula')entry.cell.formulas=[[value]];
          else entry.cell.values=[[type==='number'?Number(value):type==='boolean'?value==='true':value]];
          await ctx.sync();entry.cell.load('values,formulas,valueTypes,numberFormat,address');await ctx.sync();
          const correct=type==='formula'?entry.cell.formulas[0][0]===value:type==='number'?entry.cell.values[0][0]===Number(value):type==='boolean'?entry.cell.values[0][0]===(value==='true'):entry.cell.values[0][0]===value;
          if(!correct||entry.cell.valueTypes[0][0]==='Error'||entry.cell.numberFormat[0][0]!==JSON.parse(entry.version)[3][0][0])throw Error('readback');
          entry.version=fingerprint(entry.cell);return raw(entry.cell);
        }catch(_){throw safe('单元格写入结果尚未确认，请检查原表；不会自动重试。','uncertain');}
      });
    },
    async replace(){throw safe('单元格必须明确指定值的类型。');},
    async snapshot(id){check(id);return fullSnapshot();},
    async read_file(path){const n=await fileInfo();return samePath(n.path,path)?fullSnapshot():null;},
    async locate(id,fragment){const entry=check(id,fragment);await Excel.run(entry.cell,async ctx=>{entry.cell.select();await ctx.sync();});},
    async inspect(){return this.observe();}
  };
};
