/**
 * tarot-picker.ts — Koto 塔罗牌交互式 UI
 * Converted from tarot-picker.js
 */

export interface TarotCard {
  id: number;
  zh: string;
  en: string;
  sigil: string;
  hue: number;
  theme: string;
  revTheme: string;
}

export interface TarotSpread {
  id: string;
  label: string;
  icon: string;
  desc: string;
  tag: string;
  cards: number;
  positions: string[];
  heading: string;
  subheading: string;
  poolSize: number;
  fullWidth?: boolean;
}

export interface TarotSelectedCard {
  card: TarotCard;
  isReversed: boolean;
}

export interface TarotState {
  active: boolean;
  pendingMsg: string | null;
  suggestedSpread: TarotSpread | null;
  chosenSpread: TarotSpread | null;
  questionDetail: string;
  selectedCards: TarotSelectedCard[];
  currentPool: TarotCard[];
  allowReversed: boolean;
}

const DECK: TarotCard[] = [
  { id: 0, zh: '愚者', en: 'The Fool', sigil: '☽', hue: 220, theme: '踏入未知，新的起点，天真的冒险', revTheme: '鲁莽行事，逃避成长，悬而未决，拒绝跨出' },
  { id: 1, zh: '魔术师', en: 'The Magician', sigil: '⊛', hue: 45, theme: '意志力，创造之源，掌控现实', revTheme: '能力被误用，三心二意，自我欺骗，操控他人' },
  { id: 2, zh: '女祭司', en: 'The High Priestess', sigil: '✧', hue: 260, theme: '深层直觉，神秘知识，内在之声', revTheme: '压抑直觉，秘密泄露，过度内化，拒绝倾听自己' },
  { id: 3, zh: '女皇', en: 'The Empress', sigil: '✿', hue: 140, theme: '丰盛之源，母性力量，创造与滋养', revTheme: '创造力受阻，过度依赖，缺乏边界，滋养失衡' },
  { id: 4, zh: '皇帝', en: 'The Emperor', sigil: '⊕', hue: 15, theme: '权威与稳固，秩序的守护者', revTheme: '控制欲过强，逃避责任，失去原则，刚愎自用' },
  { id: 5, zh: '教皇', en: 'The Hierophant', sigil: '⛩', hue: 35, theme: '传统与信仰，精神引导，制度之力', revTheme: '打破旧规，质疑权威，被制度束缚，精神空洞' },
  { id: 6, zh: '恋人', en: 'The Lovers', sigil: '∞', hue: 340, theme: '深刻抉择，关系与共鸣，价值观的考验', revTheme: '价值观失衡，逃避选择，关系失调，对自我不诚实' },
  { id: 7, zh: '战车', en: 'The Chariot', sigil: '◈', hue: 200, theme: '意志的胜利，前进之力，掌控冲突', revTheme: '方向迷失，失去控制，强行推进，傲慢带来反噬' },
  { id: 8, zh: '力量', en: 'Strength', sigil: '❋', hue: 30, theme: '温柔的勇气，内在力量，耐心驯服', revTheme: '压抑情绪，自我怀疑，失去耐心，力量向内攻击' },
  { id: 9, zh: '隐士', en: 'The Hermit', sigil: '✦', hue: 270, theme: '独处的智慧，内省之旅，寻找真相', revTheme: '过度孤立，拒绝求助，固执于旧信念，逃进孤独' },
  { id: 10, zh: '命运之轮', en: 'Wheel of Fortune', sigil: '☸', hue: 60, theme: '命运的转折，周期力量，时机将至', revTheme: '抗拒变化，坏运当头，重蹈覆辙，不愿承认周期' },
  { id: 11, zh: '正义', en: 'Justice', sigil: '⚖', hue: 185, theme: '公平与因果，真相大白，平衡降临', revTheme: '逃避后果，偏见作祟，内疚未化解，对自己不公平' },
  { id: 12, zh: '倒吊人', en: 'The Hanged Man', sigil: '⟳', hue: 250, theme: '主动暂停，换个视角，放下执念', revTheme: '牺牲无效，拖延消耗，固执不放，被动悬停' },
  { id: 13, zh: '死神·变', en: 'Death', sigil: '◐', hue: 290, theme: '深刻转变，旧事终结，新生之门', revTheme: '抗拒结束，困于过去，改变迟迟未发生，死撑旧局' },
  { id: 14, zh: '节制', en: 'Temperance', sigil: '⋈', hue: 160, theme: '耐心与平衡，流动的和谐，中道之行', revTheme: '失去平衡，过激行为，自我放纵，无法整合矛盾' },
  { id: 15, zh: '恶魔', en: 'The Devil', sigil: '⛓', hue: 0, theme: '心中的枷锁，审视执着，看见束缚', revTheme: '挣脱束缚，认清上瘾，重获自主，但解脱过程痛苦' },
  { id: 16, zh: '高塔', en: 'The Tower', sigil: '⚡', hue: 25, theme: '突如其来的动荡，崩塌即启示，重建之机', revTheme: '避免灾变，内在崩塌延迟，危机在积聚，压力慢渗' },
  { id: 17, zh: '星星', en: 'The Star', sigil: '✦', hue: 210, theme: '治愈与信任，希望涌现，灵感重燃', revTheme: '失去希望，自我怀疑，理想破灭，复原力暂时耗尽' },
  { id: 18, zh: '月亮', en: 'The Moon', sigil: '◑', hue: 240, theme: '迷雾中的真相，潜意识涌动，恐惧与直觉', revTheme: '迷雾开始散去，直面恐惧，混乱慢慢平息，欺骗暴露' },
  { id: 19, zh: '太阳', en: 'The Sun', sigil: '☀', hue: 50, theme: '纯粹喜悦，明朗成功，活力四射', revTheme: '过度乐观，虚荣自满，成功延迟，喜悦被内耗遮蔽' },
  { id: 20, zh: '审判', en: 'Judgement', sigil: '◎', hue: 95, theme: '灵魂的觉醒，召唤与回应，超越过去', revTheme: '逃避觉醒，自我批评过重，内疚未化解，拒绝被召唤' },
  { id: 21, zh: '世界', en: 'The World', sigil: '⊙', hue: 170, theme: '圆满完成，整合统一，阶段的巅峰', revTheme: '未竟之事，停滞在终点前，完成的障碍，拒绝收尾' },
  { id: 22, zh: '权杖一', en: 'Ace of Wands', sigil: '⬥', hue: 22, theme: '崭新的激情与创意，事业或项目的起点，行动的火花', revTheme: '创意受阻，计划延迟，激情难以持续，鲁莽的开始' },
  { id: 23, zh: '权杖二', en: 'Two of Wands', sigil: '⬥', hue: 22, theme: '规划未来，掌控全局，勇敢展望更广的世界', revTheme: '犹豫不决，缺乏远见，固守现状，未能迈出第一步' },
  { id: 24, zh: '权杖三', en: 'Three of Wands', sigil: '⬥', hue: 22, theme: '等待成果，拓展视野，事业初见成效，信心增强', revTheme: '延迟收获，视野受限，错误预期，计划进展受阻' },
  { id: 25, zh: '权杖四', en: 'Four of Wands', sigil: '⬥', hue: 22, theme: '庆典与成就，里程碑的喜悦，稳固的根基', revTheme: '庆典推迟，家庭紧张，不稳定，喜悦被内部矛盾遮蔽' },
  { id: 26, zh: '权杖五', en: 'Five of Wands', sigil: '⬥', hue: 22, theme: '激烈的竞争与磨砺，各抒己见，在冲突中成长', revTheme: '内耗争斗，压制冲突，无建设性竞争，分歧无法化解' },
  { id: 27, zh: '权杖六', en: 'Six of Wands', sigil: '⬥', hue: 22, theme: '胜利与公众认可，凯旋归来，成就被看见', revTheme: '败局降临，失去信心，缺乏认可，自我怀疑遮蔽成就' },
  { id: 28, zh: '权杖七', en: 'Seven of Wands', sigil: '⬥', hue: 22, theme: '坚守立场，捍卫成就，逆境中的毅力', revTheme: '被压垮，放弃阵地，自信动摇，无力抵挡外部压力' },
  { id: 29, zh: '权杖八', en: 'Eight of Wands', sigil: '⬥', hue: 22, theme: '事情迅速推进，消息来临，行动加速', revTheme: '延迟，停滞，方向不明，快速推进带来混乱' },
  { id: 30, zh: '权杖九', en: 'Nine of Wands', sigil: '⬥', hue: 22, theme: '最后关头的坚韧，疲惫中仍坚守，设好防线', revTheme: '偏执的防御，拒绝援手，精力耗尽，固执成为障碍' },
  { id: 31, zh: '权杖十', en: 'Ten of Wands', sigil: '⬥', hue: 22, theme: '承担重任，在压力下全力向前，肩负使命', revTheme: '不堪重负，被责任压垮，需要卸下担子，委派他人' },
  { id: 32, zh: '权杖侍从', en: 'Page of Wands', sigil: '⬥', hue: 28, theme: '充满热情的新手，探索的好奇心，敢于尝试', revTheme: '冲动鲁莽，创意难以落地，热情无方向，虚张声势' },
  { id: 33, zh: '权杖骑士', en: 'Knight of Wands', sigil: '⬥', hue: 28, theme: '激情驱动的行动者，全速前进，勇于冒险', revTheme: '鲁莽导致失误，冲动无果，到处播种却无法完成' },
  { id: 34, zh: '权杖皇后', en: 'Queen of Wands', sigil: '⬥', hue: 28, theme: '自信与魅力，热忱的领导力，独立而充满活力', revTheme: '嫉妒心重，傲慢自大，多疑，热情转为控制欲' },
  { id: 35, zh: '权杖国王', en: 'King of Wands', sigil: '⬥', hue: 28, theme: '有远见的领袖，激情与掌控，用热情感召他人', revTheme: '专横跋扈，冲动决策，傲慢自满，热情变成压迫' },
  { id: 36, zh: '圣杯一', en: 'Ace of Cups', sigil: '⌣', hue: 205, theme: '情感的新开始，爱与直觉涌现，内心满溢的喜悦', revTheme: '情感压抑，错失感情机遇，内心干涸，无法接受爱' },
  { id: 37, zh: '圣杯二', en: 'Two of Cups', sigil: '⌣', hue: 205, theme: '深度的相互吸引，和谐伴侣，平等的情感连接', revTheme: '关系失衡，分离在即，沟通破裂，情感不对等' },
  { id: 38, zh: '圣杯三', en: 'Three of Cups', sigil: '⌣', hue: 205, theme: '友谊与庆祝，共同的喜悦，社交网络的繁荣', revTheme: '社交摩擦，过度放纵，排他性，三角关系的暗流' },
  { id: 39, zh: '圣杯四', en: 'Four of Cups', sigil: '⌣', hue: 205, theme: '无动于衷，向内收缩，对外部机遇冷漠', revTheme: '走出内省，重新接纳，抓住被忽视的好机会' },
  { id: 40, zh: '圣杯五', en: 'Five of Cups', sigil: '⌣', hue: 205, theme: '聚焦于失去，悲伤与遗憾，忽视仍然存在的美好', revTheme: '从悲伤中复原，放下执念，重新找到方向与希望' },
  { id: 41, zh: '圣杯六', en: 'Six of Cups', sigil: '⌣', hue: 205, theme: '温暖的回忆，怀旧情结，童真的善意', revTheme: '执于过去无法前行，理想化旧日，拒绝长大' },
  { id: 42, zh: '圣杯七', en: 'Seven of Cups', sigil: '⌣', hue: 205, theme: '迷失在幻想中，选择泛滥，白日梦式的可能性', revTheme: '幻象消散，面对现实，清醒判断，学会聚焦' },
  { id: 43, zh: '圣杯八', en: 'Eight of Cups', sigil: '⌣', hue: 205, theme: '主动离开不再满足之处，深层寻求，舍得放手', revTheme: '流连不去，逃避真正的告别，缺乏迈步的勇气' },
  { id: 44, zh: '圣杯九', en: 'Nine of Cups', sigil: '⌣', hue: 205, theme: '愿望成真，情感满足，内心幸福', revTheme: '物质满足却内心空洞，过度放纵，愿望未能实现' },
  { id: 45, zh: '圣杯十', en: 'Ten of Cups', sigil: '⌣', hue: 205, theme: '家庭与情感的圆满，长久的幸福，和谐共处', revTheme: '家庭矛盾，理想幸福与现实落差，情感破裂' },
  { id: 46, zh: '圣杯侍从', en: 'Page of Cups', sigil: '⌣', hue: 212, theme: '情感敏锐的探索者，创意与直觉涌现，开放的心', revTheme: '情感不成熟，多愁善感，创意受挫，逃入幻想' },
  { id: 47, zh: '圣杯骑士', en: 'Knight of Cups', sigil: '⌣', hue: 212, theme: '追逐理想，浪漫的表达，以情感驱动行动', revTheme: '情绪化，过度理想主义，情感操控，令人失望' },
  { id: 48, zh: '圣杯皇后', en: 'Queen of Cups', sigil: '⌣', hue: 212, theme: '深厚的同理心，情感滋养，以直觉洞察一切', revTheme: '情绪失控，封闭内向，无视自身需求，过度依赖他人' },
  { id: 49, zh: '圣杯国王', en: 'King of Cups', sigil: '⌣', hue: 212, theme: '情感智慧，冷静应对波动，内心平衡的领导者', revTheme: '情绪操控，压抑感受，冷漠疏离，内情失稳' },
  { id: 50, zh: '宝剑一', en: 'Ace of Swords', sigil: '⊘', hue: 88, theme: '清晰的真相，突破性的洞见，理性决断', revTheme: '混乱，误判，无益的冲突，逃避真相的代价' },
  { id: 51, zh: '宝剑二', en: 'Two of Swords', sigil: '⊘', hue: 88, theme: '暂时的僵局，信息不足时的蒙眼权衡，内心博弈', revTheme: '逃避决定的代价爆发，被误导，无路可避' },
  { id: 52, zh: '宝剑三', en: 'Three of Swords', sigil: '⊘', hue: 88, theme: '心碎与悲痛，直面痛苦现实，泪水中的诚实', revTheme: '拒绝释放痛苦，重复旧伤，自我攻击加深了伤口' },
  { id: 53, zh: '宝剑四', en: 'Four of Swords', sigil: '⊘', hue: 88, theme: '主动休整，暂时隐退，身心恢复与内省', revTheme: '惰性滋生，无法真正休息，焦虑填满了安静' },
  { id: 54, zh: '宝剑五', en: 'Five of Swords', sigil: '⊘', hue: 88, theme: '空洞的胜利，冲突的代价，需审视自私行为', revTheme: '和解，退出无谓争斗，承认失败重新开始' },
  { id: 55, zh: '宝剑六', en: 'Six of Swords', sigil: '⊘', hue: 88, theme: '离开困境，驶向平静，身心过渡中的疗愈', revTheme: '抗拒转变，沉溺旧伤，无法迈向更宁静的地方' },
  { id: 56, zh: '宝剑七', en: 'Seven of Swords', sigil: '⊘', hue: 88, theme: '策略性行动，独自为计，以智取胜', revTheme: '欺骗被揭穿，承认错误，逃避终将带来追责' },
  { id: 57, zh: '宝剑八', en: 'Eight of Swords', sigil: '⊘', hue: 88, theme: '自我设限，感觉被困，限制往往出于内心', revTheme: '解开自缚，重获视角，认清思维建造的监牢' },
  { id: 58, zh: '宝剑九', en: 'Nine of Swords', sigil: '⊘', hue: 88, theme: '焦虑与夜惊，内疚的折磨，被最坏的想象主导', revTheme: '恐惧找到出口，痛苦消散，从噩梦中清醒过来' },
  { id: 59, zh: '宝剑十', en: 'Ten of Swords', sigil: '⊘', hue: 88, theme: '痛苦的终结，触底之后，强制的了结', revTheme: '浴火重生，拒绝谷底，迟来的终结' },
  { id: 60, zh: '宝剑侍从', en: 'Page of Swords', sigil: '⊘', hue: 95, theme: '好奇多问的思考者，直率，以言语探索世界', revTheme: '八卦散布，言多必失，思维混乱，信息被滥用' },
  { id: 61, zh: '宝剑骑士', en: 'Knight of Swords', sigil: '⊘', hue: 95, theme: '快速果决地行动，锐意直前，不妥协的思想者', revTheme: '鲁莽，无视他人感受，言语如刀，冲动造成损害' },
  { id: 62, zh: '宝剑皇后', en: 'Queen of Swords', sigil: '⊘', hue: 95, theme: '清醒独立的智慧，直言不讳，以理性切割混乱', revTheme: '苛刻冷酷，封闭内心，以聪明伤害他人' },
  { id: 63, zh: '宝剑国王', en: 'King of Swords', sigil: '⊘', hue: 95, theme: '权威的逻辑与公正，掌控真相的领袖', revTheme: '专制独裁，滥用权威，用冷漠取代智慧' },
  { id: 64, zh: '星币一', en: 'Ace of Pentacles', sigil: '◇', hue: 145, theme: '物质的新机遇，财务突破，稳扎稳打的起点', revTheme: '错失物质机遇，财务不稳，积累困难，投资时机偏差' },
  { id: 65, zh: '星币二', en: 'Two of Pentacles', sigil: '◇', hue: 145, theme: '灵活平衡，应对多事，在变化中轻盈适应', revTheme: '失衡超载，优先级混乱，过度延伸导致崩溃' },
  { id: 66, zh: '星币三', en: 'Three of Pentacles', sigil: '◇', hue: 145, theme: '团队协作，精进技艺，共同创造扎实成果', revTheme: '合作失调，单打独斗，工作质量下降' },
  { id: 67, zh: '星币四', en: 'Four of Pentacles', sigil: '◇', hue: 145, theme: '掌控资源，积聚安全感，稳固积累', revTheme: '贪婪守成，执着不放，对失去的恐惧阻碍成长' },
  { id: 68, zh: '星币五', en: 'Five of Pentacles', sigil: '◇', hue: 145, theme: '物质匮乏，被排斥之感，在困境中寻求转机', revTheme: '走出困境，接受帮助，精神与物质的重新平衡' },
  { id: 69, zh: '星币六', en: 'Six of Pentacles', sigil: '◇', hue: 145, theme: '慷慨给予与接受，资源的公平分配', revTheme: '施恩图报，权力失衡，有条件的慷慨' },
  { id: 70, zh: '星币七', en: 'Seven of Pentacles', sigil: '◇', hue: 145, theme: '耐心等待收成，评估投入，长线思维', revTheme: '缺乏耐心，放弃过早，投入产出比需重新审视' },
  { id: 71, zh: '星币八', en: 'Eight of Pentacles', sigil: '◇', hue: 145, theme: '专注精进，勤勉打磨技艺，匠心学习', revTheme: '无聊的重复，缺乏精进，追求捷径，粗制滥造' },
  { id: 72, zh: '星币九', en: 'Nine of Pentacles', sigil: '◇', hue: 145, theme: '自给自足，享受劳动成果，高质量的独立生活', revTheme: '过度依赖他人，虚假的富足，所得背后有代价' },
  { id: 73, zh: '星币十', en: 'Ten of Pentacles', sigil: '◇', hue: 145, theme: '长久的富足，家族传承，代代稳固', revTheme: '家族纠纷，遗产问题，财富意义的崩塌' },
  { id: 74, zh: '星币侍从', en: 'Page of Pentacles', sigil: '◇', hue: 152, theme: '勤奋的学习者，专注实际目标，稳步起步', revTheme: '拖延怠惰，缺乏行动力，落入白日梦' },
  { id: 75, zh: '星币骑士', en: 'Knight of Pentacles', sigil: '◇', hue: 152, theme: '稳健负责，一步一脚印，忠实可靠', revTheme: '停滞不前，过于保守，拒绝改变，固步自封' },
  { id: 76, zh: '星币皇后', en: 'Queen of Pentacles', sigil: '◇', hue: 152, theme: '务实滋养，丰盛生活的掌管者，大地母亲的能量', revTheme: '安全感缺失，物质主义，自我忽视，过度执著物质' },
  { id: 77, zh: '星币国王', en: 'King of Pentacles', sigil: '◇', hue: 152, theme: '稳健的财富管理，商业智慧，慷慨而厚实的领导者', revTheme: '固执保守，吝啬或腐败，物质至上，忽视精神层面' },
];

const SPREADS: Record<string, TarotSpread> = {
  daily: {
    id: 'daily', label: '每日一牌', icon: '🌅', desc: '今日能量洞察',
    tag: '【每日一牌】', cards: 1, positions: ['今日之牌'],
    heading: '今日牌', subheading: '凭直觉翻开今天的牌', poolSize: 5,
  },
  yesno: {
    id: 'yesno', label: '是否牌', icon: '⚖️', desc: '正逆即答案',
    tag: '【是否牌】', cards: 1, positions: ['答案之牌'],
    heading: '是 / 否', subheading: '心存问题，翻开一张牌——正位倾向「是」，逆位倾向「否」', poolSize: 5,
  },
  single: {
    id: 'single', label: '单张牌', icon: '✨', desc: '通用洞察',
    tag: '【已抽出塔罗牌】', cards: 1, positions: ['你的牌'],
    heading: '选一张牌', subheading: '专注于你的问题，翻开一张牌', poolSize: 7,
  },
  three_time: {
    id: 'three_time', label: '时间三张', icon: '⏳', desc: '过去·现在·未来',
    tag: '【三张牌阵·时间之河】', cards: 3, positions: ['过去', '现在', '未来'],
    heading: '过去 · 现在 · 未来', subheading: '依次点选三张牌', poolSize: 9,
  },
  three_choice: {
    id: 'three_choice', label: '选择三张', icon: '🔀', desc: '处境·行动·结果',
    tag: '【三张牌阵·处境·行动·结果】', cards: 3, positions: ['处境', '建议行动', '可能结果'],
    heading: '处境 · 行动 · 结果', subheading: '依次点选三张牌', poolSize: 9,
  },
  relationship: {
    id: 'relationship', label: '关系牌阵', icon: '💜', desc: '你·对方·之间',
    tag: '【关系牌阵】', cards: 3, positions: ['你', '对方', '你们之间'],
    heading: '你 · 对方 · 之间', subheading: '依次点选三张牌', poolSize: 9,
  },
  celtic: {
    id: 'celtic', label: '凯尔特十字', icon: '🌀', desc: '五张深度解读', fullWidth: true,
    tag: '【凯尔特十字牌阵】', cards: 5,
    positions: ['当前处境', '挑战·阻力', '深层根基', '可能未来', '最终结果'],
    heading: '凯尔特十字', subheading: '五张深度解读，依次点选', poolSize: 13,
  },
};

const SPREAD_LIST: TarotSpread[] = [
  SPREADS.three_choice,
  SPREADS.three_time,
  SPREADS.relationship,
  SPREADS.daily,
  SPREADS.yesno,
  SPREADS.single,
  SPREADS.celtic,
];

const DRAW_PATTERN = /抽.*牌|塔罗|抽一张|帮.*抽|占卜.*牌|给我.*抽|随机.*牌|算一卦|求一签|摸一张|每日|日牌|今日.*牌|是否|能否|要不要|会不会|该不该|三张|三牌|感情|爱情|恋人|对方.*关系|凯尔特|十字|五张.*深/;

interface MoonPhase {
  name: string;
  icon: string;
  max: number;
}

const TX_LABELS: Record<string, string> = {
  daily: '今日能量聚合中...',
  yesno: '天平正在倾斜...',
  relationship: '正在解读你们之间...',
  celtic: '五张牌正在呼应...',
  three_time: '时间之河正在流动...',
  three_choice: '牌阵已成型，解读中...',
  single: '星辰正在凝视...',
};

const ROMAN = ['0', 'Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ', 'Ⅵ', 'Ⅶ', 'Ⅷ', 'Ⅸ', 'Ⅹ', 'Ⅺ', 'Ⅻ',
  'ⅩⅢ', 'ⅩⅣ', 'ⅩⅤ', 'ⅩⅥ', 'ⅩⅦ', 'ⅩⅧ', 'ⅩⅨ', 'ⅩⅩ', 'ⅩⅪ'];

const MINOR_RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'P', 'Kn', 'Q', 'K'];

let _active = false;
let _pendingMsg: string | null = null;
let _suggestedSpread: TarotSpread | null = null;
let _chosenSpread: TarotSpread | null = null;
let _questionDetail = '';
let _selectedCards: TarotSelectedCard[] = [];
let _currentPool: TarotCard[] = [];
let _autoConfirmTimer: number | null = null;
let _allowReversed = true;

let _origOnKeyDown: ((this: any, e: KeyboardEvent) => any) | null = null;
let _origOnSubmit: ((this: any, e: Event) => any) | null = null;

function detectSpread(msg: string): TarotSpread {
  if (/每日|今日.*牌|日牌|晨牌/.test(msg)) return SPREADS.daily;
  if (/是否|能否|会不会|该不该|可不可/.test(msg)) return SPREADS.yesno;
  if (/感情|爱情|他.*和.*我|我.*和.*他|恋(.{0,4})人|对方.*关系|分手|复合/.test(msg)) return SPREADS.relationship;
  if (/凯尔特|十字|五张.*深|深度.*解读/.test(msg)) return SPREADS.celtic;
  if (/选择|纠结|决定|要不要|三岔|处境/.test(msg)) return SPREADS.three_choice;
  if (/三张|三牌|过去.*未来|时间.*牌/.test(msg)) return SPREADS.three_time;
  return SPREADS.three_choice;
}

function getCardNum(card: TarotCard): string {
  return card.id < 22 ? (ROMAN[card.id] ?? '') : MINOR_RANKS[(card.id - 22) % 14];
}

function getWidget(): HTMLElement | null { return document.getElementById('tarot-picker-widget'); }

function esc(s: any): string { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function setInner(html: string): void {
  const w = getWidget();
  if (!w) return;
  w.innerHTML = html;
  w.querySelector('#tp-close-btn')?.addEventListener('click', onCancel);
  requestAnimationFrame(() => {
    const container = document.getElementById('chatMessages');
    if (container) container.scrollTop = container.scrollHeight;
  });
}

function getMoonPhase(): MoonPhase {
  const REF = 946166400000;
  const CYCLE = 29.530588 * 86400000;
  const ratio = (((Date.now() - REF) % CYCLE) + CYCLE) % CYCLE / CYCLE;
  const phases: MoonPhase[] = [
    { name: '新月', icon: '🌑', max: 0.0625 },
    { name: '蛾眉月', icon: '🌒', max: 0.1875 },
    { name: '上弦月', icon: '🌓', max: 0.3125 },
    { name: '盈凸月', icon: '🌔', max: 0.4375 },
    { name: '满月', icon: '🌕', max: 0.5625 },
    { name: '亏凸月', icon: '🌖', max: 0.6875 },
    { name: '下弦月', icon: '🌗', max: 0.8125 },
    { name: '残月', icon: '🌘', max: 0.9375 },
  ];
  return phases.find((p) => ratio < p.max) || { name: '新月', icon: '🌑', max: 1 };
}

function showSpreadScreen(): void {
  const optHtml = SPREAD_LIST.map((sp) => {
    const isSug = _suggestedSpread && sp.id === _suggestedSpread.id;
    const posHtml = sp.positions.map((p) => `<span class="tp-opt-pos-tag">${esc(p)}</span>`).join('');
    return `
      <div class="tp-spread-option${sp.fullWidth ? ' tp-spread-full' : ''}"
           data-spread-id="${sp.id}" role="button" tabindex="0" aria-label="${esc(sp.label)}">
        <div class="tp-opt-icon">${sp.icon}</div>
        <div class="tp-opt-name">${esc(sp.label)}</div>
        <div class="tp-opt-cards-badge">${sp.cards} 张</div>
        <div class="tp-opt-desc">${esc(sp.desc)}</div>
        <div class="tp-opt-positions">${posHtml}</div>
      </div>`;
  }).join('');

  setInner(`
    <button class="tp-close-btn" id="tp-close-btn" aria-label="取消" title="取消 (Esc)">×</button>
    <div class="tp-header-area">
      <div class="tp-deco-row" aria-hidden="true">✦ · ✧ · ✦</div>
      <h3 class="tp-heading">选择你的牌阵</h3>
      <p class="tp-subheading">选择一种解读方式</p>
    </div>
    <div class="tp-spread-grid" id="tp-spread-grid">${optHtml}</div>
  `);

  const grid = getWidget()?.querySelector('#tp-spread-grid');
  if (grid) {
    grid.addEventListener('click', (e: Event) => {
      const opt = (e.target as HTMLElement).closest('[data-spread-id]') as HTMLElement | null;
      if (opt) onSpreadChosen(opt.dataset['spreadId']!);
    });
    grid.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        const opt = (e.target as HTMLElement).closest('[data-spread-id]') as HTMLElement | null;
        if (opt) onSpreadChosen(opt.dataset['spreadId']!);
      }
    });
  }
}

function onSpreadChosen(spreadId: string): void {
  _chosenSpread = SPREADS[spreadId] || SPREADS.single;
  _questionDetail = '';
  showQuestionScreen();
}

function showQuestionScreen(): void {
  const sp = _chosenSpread!;
  setInner(`
    <button class="tp-close-btn" id="tp-close-btn" aria-label="取消" title="取消 (Esc)">×</button>
    <div class="tp-header-area">
      <div class="tp-deco-row" aria-hidden="true">✦ · ✧ · ✦</div>
      <div class="tp-spread-badge">${esc(sp.label)}</div>
      <h3 class="tp-heading">你想了解什么？</h3>
      <p class="tp-subheading">写下你的问题，或留空直接抽牌</p>
    </div>
    <div class="tp-question-area">
      <label class="tp-question-label" for="tp-q-input">你的问题（可留空）</label>
      <textarea id="tp-q-input" class="tp-question-input" rows="3" maxlength="200"
        placeholder="例如：这段关系值得继续吗？/ 现在适合换工作吗？"></textarea>
    </div>
    <div class="tp-question-options">
      <label class="tp-toggle-label">
        <input type="checkbox" id="tp-rev-toggle" ${_allowReversed ? 'checked' : ''}>
        <span class="tp-toggle-track"><span class="tp-toggle-thumb"></span></span>
        <span class="tp-toggle-text">开启逆位</span>
      </label>
    </div>
    <div class="tp-question-actions">
      <button class="tp-confirm-btn" id="tp-q-start">开始抽牌 →</button>
      <button class="tp-back-link" id="tp-q-back">← 换牌阵</button>
    </div>
  `);
  const w = getWidget();
  const ta = w?.querySelector('#tp-q-input') as HTMLTextAreaElement | null;
  const rev = w?.querySelector('#tp-rev-toggle') as HTMLInputElement | null;
  setTimeout(() => ta?.focus(), 80);
  const proceed = () => {
    _questionDetail = ta?.value.trim() || '';
    _allowReversed = rev?.checked ?? true;
    showBreathScreen();
  };
  w?.querySelector('#tp-q-start')?.addEventListener('click', proceed);
  w?.querySelector('#tp-q-back')?.addEventListener('click', showSpreadScreen);
  ta?.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); proceed(); }
  });
}

function showBreathScreen(): void {
  setInner(`
    <div class="tp-breath-screen">
      <div class="tp-breath-deco">✦ · ✧ · ✦</div>
      <div class="tp-breath-circle" aria-hidden="true"></div>
      <p class="tp-breath-text">将心中的问题<br>聚焦在这一刻...</p>
    </div>
  `);
  setTimeout(showCardsScreen, 1800);
}

function showCardsScreen(): void {
  const sp = _chosenSpread!;
  const isMulti = sp.cards > 1;
  _selectedCards = [];
  _currentPool = [...DECK].sort(() => Math.random() - 0.5).slice(0, sp.poolSize);

  const slotsHtml = isMulti
    ? `<div class="tp-slots" id="tp-slots">
       ${sp.positions.map((pos, i) => `
         <div class="tp-slot" id="tp-slot-${i}">
           <div class="tp-slot-pos">${esc(pos)}</div>
           <div class="tp-slot-card">?</div>
         </div>`).join('')}
       </div>
       <div class="tp-progress" id="tp-progress">已选 <span id="tp-progress-n">0</span> / ${sp.cards} 张</div>`
    : '';

  const qSummary = _questionDetail
    ? `<div class="tp-q-summary">「${esc(_questionDetail.slice(0, 45))}${_questionDetail.length > 45 ? '…' : ''}」</div>`
    : '';
  const moonHtml = sp.id === 'daily'
    ? (() => { const m = getMoonPhase(); return `<div class="tp-moon-badge">${m.icon} 今日 · ${m.name}</div>`; })()
    : '';

  setInner(`
    <button class="tp-close-btn" id="tp-close-btn" aria-label="取消" title="取消 (Esc)">×</button>
    <div class="tp-header-area">
      <div class="tp-deco-row" aria-hidden="true">✦ · ✧ · ✦</div>
      <div class="tp-spread-badge">${esc(sp.label)}</div>
      <h3 class="tp-heading">${esc(sp.heading)}</h3>
      <p class="tp-subheading">${esc(sp.subheading)}</p>
      ${qSummary}${moonHtml}
    </div>
    ${slotsHtml}
    <div class="tp-spread" id="tp-spread"></div>
    <div class="tp-actions" id="tp-actions" style="display:none">
      ${!isMulti ? '<div class="tp-selected-info" id="tp-selected-info"></div>' : ''}
      <div class="tp-btn-row">
        <button class="tp-reshuffle-btn" id="tp-reshuffle-btn">↺ 重新洗牌</button>
      </div>
      <button class="tp-back-link" id="tp-cards-back">← 换牌阵</button>
    </div>
  `);

  const w = getWidget();
  w?.querySelector('#tp-reshuffle-btn')?.addEventListener('click', onReshuffle);
  w?.querySelector('#tp-cards-back')?.addEventListener('click', () => {
    _selectedCards = [];
    showSpreadScreen();
  });

  renderPool(w?.querySelector('#tp-spread') as HTMLElement, _currentPool);
}

function renderPool(spreadEl: HTMLElement | null, pool: TarotCard[]): void {
  if (!spreadEl) return;
  spreadEl.innerHTML = '';
  const count = pool.length;
  const maxRot = Math.min(12, count * 1.4);
  pool.forEach((card, i) => {
    const rot = count > 1 ? -maxRot + (2 * maxRot / (count - 1)) * i : 0;
    const h = card.hue;
    const faceBg = `linear-gradient(160deg, hsl(${h},45%,22%) 0%, hsl(${h},50%,13%) 100%)`;
    const faceBorder = `hsl(${h},60%,50%)`;

    const wrap = document.createElement('div');
    wrap.className = 'tp-card';
    wrap.dataset['cardId'] = String(card.id);
    wrap.style.setProperty('--tp-rot', `${rot}deg`);
    wrap.innerHTML = `
      <div class="tp-card-inner">
        <div class="tp-card-back" aria-hidden="true"><div class="tp-back-sigil">✦</div></div>
        <div class="tp-card-face" style="background:${faceBg};border-color:${faceBorder}33"
             aria-label="${esc(card.zh)} ${esc(card.en)}">
          <div class="tp-face-num">${getCardNum(card)}</div>
          <div class="tp-face-sigil" style="color:hsl(${h},70%,78%)">${card.sigil}</div>
          <div class="tp-face-name-zh">${esc(card.zh)}</div>
          <div class="tp-face-name-en">${esc(card.en)}</div>
          <div class="tp-face-reversed-badge" aria-label="逆位">逆</div>
        </div>
      </div>`;
    wrap.addEventListener('click', () => onCardClick(wrap, card));
    spreadEl.appendChild(wrap);
  });
}

function onCardClick(cardEl: HTMLElement, card: TarotCard): void {
  if (cardEl.classList.contains('tp-used')) return;

  const sp = _chosenSpread!;
  const isMulti = sp.cards > 1;
  const isReversed = _allowReversed && Math.random() < 0.35;
  const slotIdx = _selectedCards.length;

  if (!isMulti) {
    const prev = getWidget()?.querySelector('.tp-card.flipped') as HTMLElement | null;
    if (prev) {
      prev.classList.remove('flipped', 'tp-selected', 'tp-used');
      prev.querySelector('.tp-card-inner')?.classList.remove('tp-reversed-flip');
      prev.querySelector('.tp-face-reversed-badge')?.classList.remove('visible');
    }
    _selectedCards = [];
  }

  if (_selectedCards.length >= sp.cards) return;

  _selectedCards.push({ card, isReversed });
  cardEl.classList.add('flipped', 'tp-selected', 'tp-used');
  if (isReversed) {
    cardEl.querySelector('.tp-card-inner')?.classList.add('tp-reversed-flip');
    cardEl.querySelector('.tp-face-reversed-badge')?.classList.add('visible');
  }

  if (isMulti) {
    fillSlot(slotIdx, card, isReversed);
    const prog = document.getElementById('tp-progress-n');
    if (prog) prog.textContent = String(_selectedCards.length);
  } else {
    const actions = document.getElementById('tp-actions');
    const info = document.getElementById('tp-selected-info');
    if (actions) actions.style.display = 'flex';
    if (info) {
      const orient = isReversed ? '（逆位）' : '（正位）';
      info.innerHTML = `
        <span class="tp-si-sigil">${card.sigil}</span>
        <span class="tp-si-name">${esc(card.zh)}<span class="tp-si-orient">${orient}</span></span>
        <span class="tp-si-en">${esc(card.en)}</span>`;
    }
    scheduleAutoConfirm();
  }

  if (isMulti && _selectedCards.length === sp.cards) {
    setTimeout(() => {
      const a = document.getElementById('tp-actions');
      if (a) { a.style.display = 'flex'; a.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
      scheduleAutoConfirm();
    }, 600);
  }
}

function fillSlot(idx: number, card: TarotCard, isReversed: boolean): void {
  const slot = document.getElementById(`tp-slot-${idx}`);
  if (!slot) return;
  slot.classList.add('tp-slot-filled');
  const el = slot.querySelector('.tp-slot-card');
  if (el) {
    const mark = isReversed
      ? '<span class="tp-slot-orient tp-slot-rev">逆</span>'
      : '<span class="tp-slot-orient tp-slot-fwd">正</span>';
    el.innerHTML = `${card.sigil} ${esc(card.zh)}${mark}`;
  }
}

function clearAutoConfirmTimer(): void {
  if (_autoConfirmTimer) { clearTimeout(_autoConfirmTimer); _autoConfirmTimer = null; }
}

function scheduleAutoConfirm(): void {
  clearAutoConfirmTimer();
  _autoConfirmTimer = window.setTimeout(() => { _autoConfirmTimer = null; onConfirm(); }, 1200);
}

function onConfirm(): void {
  const sp = _chosenSpread;
  if (!sp || _selectedCards.length < sp.cards || !_pendingMsg) return;

  const lines = _selectedCards.map(({ card, isReversed }, i) =>
    `- 第${i + 1}张（${sp.positions[i]}）：${card.zh}（${card.en}）· ${isReversed ? '逆位' : '正位'} — ${isReversed && card.revTheme ? card.revTheme : card.theme}`
  ).join('\n');

  let final = _pendingMsg;
  if (_questionDetail) final += `\n\n【我想了解的是】${_questionDetail}`;
  if (sp.id === 'daily') { const m = getMoonPhase(); final += `（今日月相：${m.name}${m.icon}）`; }
  final += `\n\n${sp.tag}\n${lines}`;

  enterTransmitState(sp, _selectedCards.slice());

  const input = document.getElementById('messageInput') as HTMLInputElement | null;
  if (input) input.value = final;

  _active = false;
  try {
    const btn = document.getElementById('sendBtn');
    if (btn) { (window as any)._kotoTarotPending = true; btn.click(); }
    else if (typeof (window as any).sendMessage === 'function') (window as any).sendMessage({ preventDefault: () => {} });
  } finally {
    _active = true;
  }
  _resetState();
}

function renderPostReadingScreen(sp: TarotSpread | null, cards: TarotSelectedCard[]): void {
  const w = getWidget();
  if (!w) return;
  const sigils = (cards || []).map(({ card, isReversed }) =>
    `<span class="tp-tx-card${isReversed ? ' tp-tx-rev' : ''}" title="${esc(card.zh)}">${card.sigil}</span>`
  ).join('');

  w.classList.remove('tp-transmitting', 'tp-dismissing');
  w.classList.add('tp-mounted', 'tp-post-reading');
  w.innerHTML = `
    <button class="tp-close-btn" id="tp-close-btn" aria-label="取消" title="取消 (Esc)">×</button>
    <div class="tp-header-area">
      <div class="tp-deco-row" aria-hidden="true">✦ · ✧ · ✦</div>
      <div class="tp-spread-badge">${esc((sp && sp.label) || '塔罗占卜')}</div>
      <h3 class="tp-heading">牌面已揭示</h3>
      <p class="tp-subheading">你可以继续在此画面抽澄清牌</p>
    </div>
    <div class="tp-tx-cards" aria-hidden="true">${sigils}</div>
    <div class="tp-actions" style="display:flex; margin-top: 8px;">
      <div class="tp-btn-row" style="width:100%;">
        <button class="tp-confirm-btn" id="tp-clarifier-in-widget">✦ 抽一张澄清牌</button>
      </div>
    </div>`;

  w.querySelector('#tp-close-btn')?.addEventListener('click', onCancel);
  w.querySelector('#tp-clarifier-in-widget')?.addEventListener('click', () => {
    if ((window as any).TarotPicker && typeof (window as any).TarotPicker.drawClarifier === 'function') {
      (window as any).TarotPicker.drawClarifier();
    }
  });
}

function enterTransmitState(sp: TarotSpread, cards: TarotSelectedCard[]): void {
  const w = getWidget();
  if (!w) return;

  const txLabel = TX_LABELS[sp.id] || '星辰正在凝视...';
  const cardSigils = cards.map(({ card, isReversed }) =>
    `<span class="tp-tx-card${isReversed ? ' tp-tx-rev' : ''}" title="${esc(card.zh)}">${card.sigil}</span>`
  ).join('');

  w.innerHTML = `
    <div class="tp-transmit-overlay">
      <div class="tp-tx-deco">✦ · ✧ · ✦</div>
      <div class="tp-tx-cards" aria-hidden="true">${cardSigils}</div>
      <div class="tp-tx-label">${txLabel}</div>
      <div class="tp-tx-dots"><span></span><span></span><span></span></div>
    </div>`;
  w.classList.add('tp-transmitting');

  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    observer.disconnect();
    setTimeout(() => {
      if (w.parentNode) {
        renderPostReadingScreen(sp, cards);
      }
    }, 900);
  };

  const container = document.getElementById('chatMessages');
  if (!container) {
    setTimeout(() => { renderPostReadingScreen(sp, cards); }, 900);
    return;
  }

  const observer = new MutationObserver(() => {
    const lastMsg = container.lastElementChild;
    if (lastMsg && lastMsg.classList.contains('assistant')) {
      dismiss();
    }
  });
  observer.observe(container, { childList: true });

  setTimeout(dismiss, 15000);
}

function onCancel(): void { removePicker(); _resetState(); }

function onReshuffle(): void {
  clearAutoConfirmTimer();
  const sp = _chosenSpread;
  if (!sp) return;
  const actionsEl = document.getElementById('tp-actions');
  if (actionsEl) actionsEl.style.display = 'none';
  _selectedCards = [];
  if (sp.cards > 1) {
    sp.positions.forEach((_, i) => {
      const slot = document.getElementById(`tp-slot-${i}`);
      if (slot) { slot.classList.remove('tp-slot-filled'); const c = slot.querySelector('.tp-slot-card'); if (c) c.textContent = '?'; }
    });
    const prog = document.getElementById('tp-progress-n');
    if (prog) prog.textContent = '0';
  }
  _currentPool = [...DECK].sort(() => Math.random() - 0.5).slice(0, sp.poolSize);
  renderPool(document.getElementById('tp-spread'), _currentPool);
}

function _resetState(): void {
  clearAutoConfirmTimer();
  _pendingMsg = null;
  _suggestedSpread = null;
  _chosenSpread = null;
  _questionDetail = '';
  _allowReversed = true;
  _selectedCards = [];
  _currentPool = [];
}

function _createWidgetEl(): HTMLElement | null {
  removePicker();
  const el = document.createElement('div');
  el.id = 'tarot-picker-widget';
  el.className = 'tarot-picker-widget';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', '塔罗牌选择');
  const container = document.getElementById('chatMessages');
  if (!container) return null;
  container.querySelector('.welcome-screen')?.remove();
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  function escHandler(e: KeyboardEvent) {
    if (e.key === 'Escape') { document.removeEventListener('keydown', escHandler); onCancel(); }
  }
  document.addEventListener('keydown', escHandler);
  return el;
}

export function showPicker(originalMessage: string): void {
  _pendingMsg = originalMessage;
  _suggestedSpread = detectSpread(originalMessage);
  _chosenSpread = null;
  _questionDetail = '';
  _selectedCards = [];
  const el = _createWidgetEl();
  if (!el) return;
  requestAnimationFrame(() => { el.classList.add('tp-mounted'); showSpreadScreen(); });
}

function removePicker(): void {
  const el = document.getElementById('tarot-picker-widget');
  if (el) { el.classList.add('tp-dismissing'); setTimeout(() => el.remove(), 300); }
  _selectedCards = [];
}

function hasPersistentTarotUI(): boolean {
  return Boolean(
    document.getElementById('tarot-picker-widget') ||
    document.querySelector('.tp-clarifier-row') ||
    (window as any)._kotoTarotPending
  );
}

function hookSendMessage(): void {
  const input = document.getElementById('messageInput');
  const form = document.querySelector('.chat-input-form') as HTMLFormElement;

  if (input && !(input as any).dataset?.['tarotHooked']) {
    _origOnKeyDown = (input as any).onkeydown;
    (input as any).onkeydown = function (this: any, e: KeyboardEvent) {
      if (_active && e.key === 'Enter' && !e.shiftKey && !(e as any).isComposing && (e as any).keyCode !== 229) {
        const msg = (input as HTMLInputElement).value.trim();
        if (msg) {
          e.preventDefault(); _pendingMsg = msg; (input as HTMLInputElement).value = ''; showPicker(msg); return false;
        }
      }
      return _origOnKeyDown ? _origOnKeyDown.call(this, e) : undefined;
    };
    (input as any).dataset['tarotHooked'] = '1';
  }

  if (form && !(form as any).dataset?.['tarotHooked']) {
    _origOnSubmit = (form as any).onsubmit;
    (form as any).onsubmit = function (this: any, e: Event) {
      if (_active) {
        const inp = document.getElementById('messageInput') as HTMLInputElement;
        const msg = inp ? inp.value.trim() : '';
        if (msg) {
          e?.preventDefault(); _pendingMsg = msg; if (inp) inp.value = ''; showPicker(msg); return false;
        }
      }
      return _origOnSubmit ? _origOnSubmit.call(this, e) : undefined;
    };
    (form as any).dataset['tarotHooked'] = '1';
  }
}

function unhookSendMessage(): void {
  const input = document.getElementById('messageInput');
  const form = document.querySelector('.chat-input-form') as HTMLFormElement;
  if (input && (input as any).dataset?.['tarotHooked']) { (input as any).onkeydown = _origOnKeyDown; delete (input as any).dataset['tarotHooked']; }
  if (form && (form as any).dataset?.['tarotHooked']) { (form as any).onsubmit = _origOnSubmit; delete (form as any).dataset['tarotHooked']; }
}

export function setTarotActive(active: boolean): void {
  _active = Boolean(active);
  if (_active) hookSendMessage();
  else {
    if (hasPersistentTarotUI()) {
      _active = true;
      hookSendMessage();
      return;
    }
    unhookSendMessage();
    removePicker();
    _resetState();
  }
}

export function drawClarifier(): void {
  if (!_active) {
    _active = true;
    hookSendMessage();
  }
  document.querySelector('.tp-clarifier-row')?.remove();
  _pendingMsg = '（澄清解读，针对上一张牌的疑问）';
  _suggestedSpread = null;
  _chosenSpread = Object.assign({}, SPREADS.single, {
    heading: '澄清牌',
    subheading: '心存疑问，再翻一张',
    tag: '【澄清牌】',
  });
  _questionDetail = '';
  _selectedCards = [];
  const el = _createWidgetEl();
  if (!el) return;
  requestAnimationFrame(() => { el.classList.add('tp-mounted'); showCardsScreen(); });
}

export function isPersistentActive(): boolean {
  return hasPersistentTarotUI();
}

export function initTarotPicker(): void {
  // Exists as a no-op init hook; actual activation is via setTarotActive
}

// Backward compat
(window as any).KotoTarot = {
  TarotPicker: {
    setActive: setTarotActive,
    drawClarifier: drawClarifier,
    isPersistentActive: isPersistentActive,
  },
};

if ((window as any).SkillUI?.refresh) (window as any).SkillUI.refresh();
