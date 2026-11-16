/* Test contract only. No real Excel is launched. */
window.fixtureWrites=0;window.fixtureProtection=false;window.fixtureMerged=false;window.fixtureSpill=false;
window.fixtureGrid=[['项目','金额','备注'],['研发',120.1,'保留备注'],['运营',79.9,'另一个备注'],['合计',200,''],['尾部',7,'保持不变']];
window.fixtureFormulas={'3,1':'=SUM(B2:B3)'};window.fixtureFormats={};window.fixtureSelection={r:1,c:1,rows:2,cols:1};
function recalculate(){if(fixtureFormulas['3,1']==='=SUM(B2:B3)')fixtureGrid[3][1]=Number(fixtureGrid[1][1])+Number(fixtureGrid[2][1]);}
class CellRange {
  constructor(context,r,c,rows=1,cols=1){Object.assign(this,{context,r,c,rowCount:rows,columnCount:cols});}
  load(){return this;}select(){window.fixtureLocated=this.address;}
  get address(){return '预算!'+String.fromCharCode(65+this.c)+(this.r+1)+(this.rowCount*this.columnCount>1?':'+String.fromCharCode(65+this.c+this.columnCount-1)+(this.r+this.rowCount):'');}
  get worksheet(){return new Worksheet(this.context);}
  get values(){return fixtureGrid.slice(this.r,this.r+this.rowCount).map(row=>row.slice(this.c,this.c+this.columnCount));}
  set values(value){fixtureGrid[this.r][this.c]=value[0][0];delete fixtureFormulas[this.r+','+this.c];fixtureWrites++;recalculate();}
  get formulas(){return this.values.map((row,r)=>row.map((value,c)=>fixtureFormulas[(this.r+r)+','+(this.c+c)]??value));}
  set formulas(value){fixtureFormulas[this.r+','+this.c]=value[0][0];fixtureWrites++;recalculate();}
  get text(){return this.values.map(row=>row.map(String));}
  get valueTypes(){return this.values.map(row=>row.map(value=>typeof value==='number'?'Double':typeof value==='boolean'?'Boolean':value===''?'Empty':'String'));}
  get numberFormat(){return this.values.map((row,r)=>row.map((_,c)=>fixtureFormats[(this.r+r)+','+(this.c+c)]||'0.00'));}
  get hasSpill(){return fixtureSpill;}
  getCell(r,c){return new CellRange(this.context,this.r+r,this.c+c);}
  getMergedAreasOrNullObject(){return {isNullObject:!fixtureMerged};}
}
class Worksheet {
  id='sheet1';name='预算';
  constructor(context){this.context=context;}
  load(){return this;}
  get protection(){return {get protected(){return fixtureProtection;},load(){return this;}};}
  getUsedRangeOrNullObject(){return new CellRange(this.context,0,0,5,3);}
}
function excelContext(){const ctx={sync:async()=>{},trackedObjects:{add(){},remove(){}}};ctx.workbook={getSelectedRange:()=>new CellRange(ctx,fixtureSelection.r,fixtureSelection.c,fixtureSelection.rows,fixtureSelection.cols),worksheets:{items:[new Worksheet(ctx)],load(){return this;}}};return ctx;}
window.Office={onReady:async()=>({host:'Excel'}),context:{requirements:{isSetSupported:()=>true},document:{mode:'readWrite',getFilePropertiesAsync:callback=>callback({status:'succeeded',value:{url:'C:/synthetic/预算.xlsx'}})}}};
window.Excel={run:async(objects,work)=>{if(typeof objects==='function')return objects(excelContext());const list=Array.isArray(objects)?objects:[objects];if(!list.every(item=>item.context===list[0].context))throw Error('InvalidRequestContext');return work(list[0].context);}};
