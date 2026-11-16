/* Simulated WPS ranges for transport tests; never native WPS acceptance. */
window.fixtureText='本季度营收达到240万元，同比增长20%，但还需要继续分析原因。\r下一季度我们会改进客户转化流程，并加强线索质量检查，提升团队工作效率。\r这段保持不变。\r';
window.fixtureWrites=0;
const fixtureRanges=new Set();
class FixtureWpsRange {
  constructor(start,end){
    this.Start=start;this.End=end;this.StoryType=1;
    this.Font={Bold:0,Italic:0,Underline:0,Size:12,Color:0,Hidden:0,StrikeThrough:0,NameAscii:'Arial',NameFarEast:'宋体',NameOther:'Arial',NameBi:'Arial'};
    for(const key of ['Fields','InlineShapes','Hyperlinks','ContentControls'])this[key]={Count:0};
    fixtureRanges.add(this);
  }
  get Text(){return fixtureText.slice(this.Start,this.End);}
  set Text(value){
    const start=this.Start,end=this.End,delta=value.length-(end-start);
    fixtureText=fixtureText.slice(0,start)+value+fixtureText.slice(end);
    for(const range of fixtureRanges){
      if(range===this){range.End=start+value.length;continue;}
      if(range.End<=start)continue;
      if(range.Start>=end){range.Start+=delta;range.End+=delta;continue;}
      if(range.Start>=start)range.Start=start;
      range.End=range.End<=end?start+value.length:range.End+delta;
    }
    fixtureWrites++;
  }
  get Duplicate(){return new FixtureWpsRange(this.Start,this.End);}
  get Paragraphs(){
    const spans=[];let start=0;
    for(const text of fixtureText.split('\r')){
      const end=start+text.length+1;
      if(text&&(this.Start===this.End?start<=this.Start&&this.Start<end:start<this.End&&end>this.Start))spans.push([start,end]);
      start=end;
    }
    return {Count:spans.length,Item:index=>({Range:new FixtureWpsRange(...spans[index-1])})};
  }
  Select(){window.fixtureSelection=this.Duplicate;}
}
window.fixtureSelection=new FixtureWpsRange(0,fixtureText.indexOf('\r',fixtureText.indexOf('\r')+1));
const fixtureDocument={Name:'WPS合成测试.docx',FullName:'C:/synthetic/WPS合成测试.docx',Saved:false,ReadOnly:false,ProtectionType:-1,
  Range:(start,end)=>new FixtureWpsRange(start,end),get Content(){return new FixtureWpsRange(0,fixtureText.length);}};
window.wps={get Selection(){return {Range:fixtureSelection};},ActiveDocument:fixtureDocument,Documents:{Count:1,Item:()=>fixtureDocument}};
