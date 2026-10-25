# Changelog / 更新日志

All notable changes, newest first. Entries are bilingual: English / 中文.
There are no version numbers yet; the bot is deployed from `main` with `deploy/push.sh`.

## 2026-10-25

### Changed / 修改
- **No guess when the model fails.** When Groq's free tier answered 429, the RAG step errored and the bot sent the
  rules' weak guess, such as "你问的是不是…" for "马莫和诺丁汉哪个好" and unrelated official pages for "计算机专业毕业起薪多少".
  Now a weak Q&A match, or only the Hub's loosely related pages, goes to the owner whenever the model gives no checked
  answer (error, timeout, no quote, or no passage close enough to ask it). An article or the Hub's FAQ is still sent. /
  模型出错时不再瞎猜：Groq 免费额度返回 429 时，RAG 出错，机器人就发规则的弱匹配，比如「马莫和诺丁汉哪个好」回「你问的是不是…」，「计算机专业毕业起薪多少」回一串不相关的官方页面。现在只要模型没给出核对过的答案（出错、超时、没摘到句子、或者没有够近的资料可问），弱匹配的问答和只有相关官方页面的答案都转给作者。公众号文章和 Hub FAQ 的答案照常发。

### Added / 新增
- **Choosing units for a year, and the visa during exchange**, in the owner's words. "莫纳什的选课是一学期一学期的选吗"
  got an Australian summer-semester sentence: WES usually needs the whole year (4 units in each semester) before it
  submits, changes are possible until Friday of Week 2, and S1 comes first because class times are chosen before the
  semester. "交换需要消签吗" went to the owner: students coming back to Malaysia should renew and keep the Student Pass,
  and the destination's visa is separate. "毕业要销签吗" and "学生签证要注销吗" now reach the graduation Q&A, which says
  how to cancel the Student Pass (the last one used to match the part-time work Q&A). / 按作者的话新增两条问答：「莫纳什的选课是一学期一学期的选吗」以前摘的是澳洲夏季学期的一句，现在答 WES 一般要先选满一整年（两个学期各 4 门）才能提交，第 2 周周五前能自己调整，先定 S1 的课，因为开学前要选上课时间。「交换需要消签吗」以前转给作者，现在答交换后还回马莫读的建议续签保留 Student Pass，目的地签证另外申请。「毕业要销签吗」「学生签证要注销吗」现在命中毕业问答里注销 Student Pass 的说明（后者以前会匹配到打工问答）。
- **Several messages the bot cannot answer reach the owner as one note.** On 2026-10-24 a student's question in
  three short messages became three 待答 notes, and the owner had to piece them together. The note now waits until
  the asker has sent nothing for 90 seconds (`WXBOT_PENDING_QUIET_S`) and has every line the bot could not answer,
  plus what else they asked then (a line the bot did answer, like "然后现在他要我交学费", is context). The asker is told
  "已经转给 Waldo" once. A miss within 30 minutes (`WXBOT_PENDING_MERGE_S`) while the question is open joins it, and
  the owner gets it as a supplement. `答 N` on several lines replies but does not store a Q&A, since the lines are not
  one phrasing. Old databases get the new columns on start, and their open questions are not sent again. / 答不上来的几句合成一条转给作者：10-24 有同学把一个问题分三句发，作者收到三条待答，要自己拼起来。现在待答通知会等提问人 90 秒（`WXBOT_PENDING_QUIET_S`）没再发新的，再把机器人答不上来的几句合成一条发，附上同一时间问过、机器人答了的话（比如「然后现在他要我交学费」）当前后文。提问人只收到一次「已经转给 Waldo」。问题还没处理、30 分钟内（`WXBOT_PENDING_MERGE_S`）又答不上来的，追加到同一条，作为补充发给作者。几句合起来的用「答 N」回复后不存成问答。旧数据库启动时自动加新字段，已有的待答不会重发。
- **How many units a semester.** "一学期修几门课" fell through to the model, which quoted the underload Q&A with its
  campus label in the middle of the quote. A new Q&A answers first (full time is usually 4 units, 24 credit points a
  semester, 48 a year), then introduces overload and underload in a line each and names the questions that give the
  details; Australia has the same standard load. / 新增“一学期修几门课”问答：之前走模型，摘的是减课问答里带校区标签的一句。新问答先答全日制一般每学期 4 门课、24 学分（一年 48 学分），再各用一行介绍多修（overload）和减课（underload），并告诉学生去问哪条看详细；澳洲校区标准一样。
- **Underload and the visa, for each campus.** "国际学生减课会影响签证吗" reached only the Hub FAQ's vague "可能影响签证".
  The new Q&A gives Malaysia's rule (at least 18 credit points a semester, only in the listed cases, with evidence;
  below 18 is intermission; when no approval is needed) and Australia's (only in compassionate or compelling
  circumstances), and how to apply in Malaysia from the SORS form's own notes (the Underload Application link, email
  the International Student Pass Office first, by Friday of Week 2, scholarship and loan checks). A new overload Q&A
  gives the form's conditions (48 credit points in two consecutive semesters, a 60% credit average), at most one
  extra unit, the SORS link and the Week 2 deadline. / 减课和签证分校区写：“国际学生减课会影响签证吗”之前只摘到 Hub FAQ 一句“可能影响签证”。新问答写马莫规定（每学期最少 18 学分，只限几种情况；低于 18 学分要休学；哪些情况不用申请）、按 SORS 表格说明写的申请方法（Underload Application 链接、提交前先发邮件问 ISP、开学第 2 周周五前、奖学金和贷款要先问），和澳洲规定（只有特殊情况才能减课）。新增多修课（overload）问答：条件（连续两学期修满 48 学分、平均分 60% 以上）、最多加 1 门、SORS 链接和第 2 周截止。
- **Rules that differ by country are given for each campus, labelled.** The owner (2026-10-25): the student visa,
  medical insurance and the like are not the same in Malaysia and Australia, so an answer must say which is which.
  - "休学会影响学生签证吗" was answered with the Hub FAQ's "休学会改变你的 CoE"; CoE is part of the Australian student
    visa. A new Q&A follows the Malaysia "During Your Studies" page (at most two semesters or one year; medical
    intermission can stay with a valid Student Pass, any other must cancel it and leave; coming back needs a new eVAL
    through ISP) and adds the Australian rule (only in compassionate or compelling circumstances; it affects the CoE).
  - Renewal, an expired visa, insurance and withdrawing a unit now give 【马来西亚校区】 and 【澳洲校区】 separately: the
    Australian visa (subclass 500) is applied for again, not renewed; Australia uses OSHC (Allianz), not Generali; an
    underload in Malaysia is at least 18 credit points with approval. Attendance and visa lines that are Malaysia
    rules now say 马莫.
  - New Q&As for part-time work (Malaysia: breaks over 7 days, 20 hours a week, listed jobs, approval through ISP;
    Australia: 48 hours a fortnight) and transferring to another university (Malaysia: cancel the Student Pass;
    Australia: a release unless 12 months studied).
  - RAG no longer leaves out what is about Australia. A sentence from an Australian campus page or with an
    Australia-only term (CoE, OSHC, ESOS, Centrelink, HECS-HELP, FEE-HELP, OS-HELP, "在澳") goes last, under
    "澳洲校区（澳大利亚的规定，马来西亚校区不一定一样）：", after the Malaysia and every-campus ones. A Malaysia page is
    kept next to the Hub's FAQ (only a taught answer stands alone). Up to 4 quotes instead of 3.
  - "期末考试要带什么" and "考试要带什么" now reach the exam items Q&A.
  - The graduation Q&A adds what the owner had from the graduations office: after finishing, conferral can be
    deferred up to 3 months in the system, and up to 12 months after completion through Monash Connect for needs
    such as a graduate programme; the testamur shows the actual conferral date.
  - The exchange Q&A says GIP (Global Intercampus Program) is now called Semester in Australia (SIA), with its page.
  / 按国家不同的规定分校区写清楚（用户 10-25：学生签证、医疗保险等马莫和澳洲不一样，回答要分开写明）：“休学会影响学生签证吗”之前引用 Hub FAQ 的“休学会改变你的 CoE”，CoE 是澳洲签证的东西。新问答按马莫官网写（最多两个学期或一年；医疗原因休学可留在马来西亚但 Student Pass 要有效，其他原因要注销离境；回来要通过 ISP 重新申请 eVAL），并附澳洲规定。续签、签证过期、保险、退课改成【马来西亚校区】【澳洲校区】分开写；出勤和签证相关的马莫规定写明“马莫”。新增打工和转学两条问答，两个校区分开写。RAG 不再删澳洲的内容，而是放在最后，标“澳洲校区”；Hub FAQ 旁边保留马来西亚官网的句子；最多摘 4 句。“期末考试要带什么”会答考场带什么。毕业问答补上学位授予延期（毕业事务部门确认：系统里最多延 3 个月，特殊需要经 Monash Connect 最长到课程完成后 12 个月，证书显示实际授予日期）。交换问答写明 GIP 现在官网叫 Semester in Australia（SIA）。

- **Seven Q&As for questions the eighth evaluation round missed**, written from the official Monash Malaysia pages:
  international student medical insurance (Generali, MiCare, how to claim), where to find semester breaks (Principal
  Dates), withdrawing from a unit (census date, WD-LATE / WD-FAIL, the SORS form), what to bring into an on-campus
  eExam, unpaid fees and encumbrance, the free Sunway shuttle bus, and PTPTN (Malaysian citizens only). "怎么退课" moves
  from the enrolment Q&A to the new one; "校车", "shuttle bus" and "穿梭巴士" move from the transport Q&A to the
  shuttle one. "作业交完要注意什么" and "student pass什么时候可以续" are new phrasings of the submission and renewal Q&As.
  / 第八轮评测没答上的问题加了 7 条问答，都按马莫官网原文写：国际生医疗保险（Generali、MiCare、怎么理赔）、放假时间在哪查（Principal Dates）、退课（census date、WD-LATE / WD-FAIL、SORS 表格）、校内 eExam 要带什么、欠费和 encumbrance、Sunway 免费穿梭巴士、PTPTN（只有马来西亚公民能申请）。“怎么退课”从选课问答移到新的退课问答，“校车”“shuttle bus”“穿梭巴士”从交通问答移到校车问答。“作业交完要注意什么”和“student pass什么时候可以续”加成交作业和续签问答的问法。

### Fixed / 修复
- **Degrees ignored the Handbook year.** "C2001 2026年要学什么" got the 2027 Handbook card, and so did every degree
  while `WXBOT_HUB_YEAR` pins 2026 for units. Degrees now use the same year as units; a year that does not list the
  degree falls back to the Hub's default year and says which year was asked for. / 专业不看 Handbook 年份：「C2001 2026年要学什么」回的是 2027 版，`WXBOT_HUB_YEAR` 设成 2026 时课程按 2026 答，专业却一律是 2027 版。现在专业和课程用同一个年份；那一年没有这个专业时，改用 Hub 默认年份，并说明问的那年没有。
- **Degree codes that look like a year.** Since the Handbook year could be typed in the question (#36, 2026-10-24),
  the digits of B2026 or M2018 were read as the year 2026 or 2018, the degree was lost, and "B2026要学什么课" and
  "m2018属于哪个faculty" went to the owner (they were answered on 2026-10-07 and 2026-10-23). Degree codes are now kept
  like unit codes. Found by the evaluation on 50 real questions. / 专业代码被当成年份：#36（10-24，可以在问题里写 Handbook
  年份）之后，B2026、M2018 里的数字被当成 2026 年、2018 年去掉，专业就查不到了，「B2026要学什么课」「m2018属于哪个faculty」转给了作者（10-07 和 10-23 还能答）。现在专业代码和课程代码一样先保留。用 50 道真实问题评测时发现。
- **RAG kept dropping right sentences.** Found in the eighth evaluation round:
  - A sentence naming a past year was dropped even when the rule still runs ("2025 年 3 月 1 日起…过渡期到 2026 年
    12 月 31 日" for the hurdle question). Now it is dropped only when all of its years are past.
  - "在澳洲以外的校区（比如马来西亚）" was dropped as an Australia sentence. "澳洲以外" and "outside Australia" no
    longer count.
  - The expired-visa Q&A answered "休学会影响学生签证吗" because of its short phrasing "学生签证过期了". That phrasing
    is gone and "Student Pass过期了" is now "Student Pass过期了怎么办".
  / RAG 误删了对的句子（第八轮评测发现）：写了往年年份的句子即使规则还在生效也被删（hurdle 问题里的“2025 年 3 月 1 日起…过渡期到 2026 年 12 月 31 日”），现在只有句子里的年份全是往年才删；“在澳洲以外的校区（比如马来西亚）”被当成澳洲的句子删了，现在“澳洲以外”和“outside Australia”不算。签证过期的问答因为短问法“学生签证过期了”把“休学会影响学生签证吗”也答成了签证过期，去掉了这个问法，“Student Pass过期了”改成“Student Pass过期了怎么办”。

## 2026-10-24

### Changed / 修改
- **A unit's teach-out notice is the Malaysia campus one.** The Hub's notice has one entry per faculty page, each
  marked `applies_to`. The bot showed the first one, so FIT2004 got the Australian IT page's entry and link ("BCS, BSE")
  instead of the Malaysia page's ("BCS, BCS in DS, BCS in AI, BSE"). It now shows the entries for `WXBOT_HUB_CAMPUS`
  with their own link; a change only the Australian page lists (FIT1049) is shown and labelled as such.
  / 课程的停开通知改用马来西亚校区的：Hub 的通知按学院页面分条，每条标了 `applies_to`。机器人之前只拿第一条，所以 FIT2004 显示的是澳洲 IT 学院页面的内容和链接（BCS, BSE），不是马来西亚页面的（BCS, BCS in DS, BCS in AI, BSE）。现在只显示 `WXBOT_HUB_CAMPUS` 校区的条目和对应链接；只有澳洲页面写了的变动（如 FIT1049）照样显示，但会注明。
- **Monash Hub ranks Malaysia pages first.** Every `/ask` call now sends `"campus": "malaysia"` (Monash Hub #209), so a
  Malaysia page beats an Australian one on the same topic ("转专业" found the Australian internal-transfer page).
  `WXBOT_HUB_CAMPUS` changes it; empty sends nothing. Deploy after the Hub's #209 is live.
  / Monash Hub 优先给马来西亚校区的页面：每次调 `/ask` 都带 `"campus": "malaysia"`（Monash Hub #209），同一个话题马来西亚页面排在澳洲页面前面（之前“转专业”找到的是澳洲的页面）。用 `WXBOT_HUB_CAMPUS` 改，留空就不传。要等 Hub 的 #209 上线后再部署。
- **Taught answer for changing course at Monash Malaysia.** Asked "转专业是符合转的要求就可以还是择优录取啊", the
  RAG answer quoted the Australian internal-transfer page: the Malaysia page is in the index but its Chinese text says
  "转学位课程", never "转专业". The new Q&A is written from the Malaysia Internal Course Transfer page (eligibility,
  the form, the February 2027 dates, accepting the offer, the new Student Pass) and the IT school's note that selection
  is competitive. The dates are for the February 2027 intake and need updating after it.
  / 新增马莫转专业问答：问“转专业是符合转的要求就可以还是择优录取啊”时，RAG 摘了澳洲校区的转专业页面。马来西亚的页面在索引里，但中文写的是“转学位课程”，没有“转专业”。新问答按马来西亚 Internal Course Transfer 页面（条件、申请表、2027 年 2 月入学的日期、接受 offer、重新办签证）和信息技术学院“转学位是竞争性选拔”的说明写。日期是 2027 年 2 月入学的，过了要更新。线上要重新导入 `qa/mamo-topics.json`。
- **Ask Mira is gone: answers point to MoVA and Monash Connect.** Monash switched Ask Mira off in October 2026. Online
  help is now MoVA (https://www.monash.edu.my/student-services/connect?chatbot=open), and the Student Hub became
  Monash Connect (Building 3, Level 1; Mon–Thu 9am–5pm, Fri 9am–1pm, from Monash's email). The enrolment, timetable,
  attendance, websites, arrival and Monash Connect answers say so, and a new Q&A answers "AskMira用不了 / MoVA是什么".
  The RAG answer no longer quotes a sentence that sends students to Ask Mira, since old articles and some official
  pages still do.
  / Ask Mira 停用，答案改成 MoVA 和 Monash Connect：Monash 2026 年 10 月停用了 Ask Mira，线上咨询改用 MoVA，Student Hub 改名 Monash Connect（3 号楼 1 层；周一到周四 9:00–17:00，周五 9:00–13:00，按学校邮件）。选课、排课、出勤、常用网站、报到和 Monash Connect 几条答案都改了，新增“AskMira用不了 / MoVA是什么”问答。旧推文和部分官网页面还写着 Ask Mira，RAG 不再摘这类句子。线上要 `import-qa --replace`。
- **Taught answers for questions the bot could not answer, and no direct answer when two are as close.** From the
  live log: a WES submission where only some units went through, a make-up class that clashes, public holidays, minor
  and elective, printing, Monash Connect in person, MDAC, opening a bank account, the 2027 Handbook, when and where final
  exams are and an expired student pass, all with Waldo's answers. Moodle and the campus map get more phrasings (作业会发到哪里,
  plenary 在哪). "期末考试" is rare, so "期末考试在哪考" scored 0.80 against "期末考试什么时候" and 0.79 against the
  defer answer. A strong match now answers directly only when the next taught answer is at least `WXBOT_QA_MARGIN`
  (0.03) behind; otherwise it is "你问的是不是…" and the RAG answer is asked. No phrasing in the file and no question
  in `eval/questions.jsonl` changes. An answer Waldo gave from his own experience can have no link.
  / 按线上记录补教没答上的问题，两个答案一样接近时不直接回答：WES 提交后只选上一部分、补课撞课、公共假期、minor 和 elective、打印、Monash Connect 面对面咨询、MDAC、银行开户、2027 Handbook、期末考试时间和地点、学生签证过期，答案都是 Waldo 给的。Moodle 和校园地图加了问法（作业会发到哪里、plenary 在哪）。“期末考试”这个词很少见，“期末考试在哪考”对“期末考试什么时候”得 0.80，对缓考那条得 0.79。现在强匹配要比第二接近的问答高出 `WXBOT_QA_MARGIN`（0.03）才直接回答，否则按“你问的是不是…”处理，并且会问 RAG。问答文件里的问法和 `eval/questions.jsonl` 的问题结果都没变。Waldo 凭经验给的答案可以不带链接。线上要重新导入 `qa/mamo-topics.json`。
- **The RAG answer no longer quotes table rows or past years.** Asked "期末考试什么时候" on 2026-10-24, it sent
  "10 月入学（马来西亚） | OCT-MY-01 | 2025年1月6日 | …": verbatim, but one intake's row from last year with no header.
  A quote with " | " or a year before this one is now left out like other quotes that need their context.
  / RAG 不再摘表格行和往年的句子：2026-10-24 问“期末考试什么时候”，它摘了“10 月入学（马来西亚） | OCT-MY-01 | 2025年1月6日 | …”，字是原文，但只是去年某一批入学的一行，也没有表头。带“ | ”或年份早于今年的句子，现在和其他离开上下文会看错的句子一样不发。
- **Taught answer for deferring a final exam.** The Hub FAQ the RAG answer quoted said deferring a final exam has no
  form of its own; the official defer page links a separate one (forms.monash.edu/deferred-and-rescheduled-assessments).
  The new Q&A is written from that page, its form and the Monash Malaysia exams FAQ. Its phrasings avoid "期末考试",
  which would have pulled in every question about exams. The extension answer now points to it.
  / 新增“期末考试缓考”的问答：RAG 摘到的 Hub FAQ 说期末缓考没有单独的表格，官网缓考页其实链接到单独的表格。答案按官网缓考页、申请表和马莫考试 FAQ 写。问法里没有用“期末考试”，否则会把所有问考试的问题都吸过来。延期那条答案改为指向它，线上要用 `import-qa --replace` 重新导入。
- **Taught answers for being ill with work due, and more ways to ask about resits.** A new Q&A in
  `qa/mamo-topics.json` covers short extensions and special consideration from the official extensions page, its
  documents page and the application form (one form for both; apply by 11.55pm on the due date). The resit Q&A gets
  phrasings such as "挂了一门有补考吗", which the RAG answer could not quote safely, so it went to the owner.
  / 新增“生病交不了作业”的问答：按官网延期页、证明材料页和申请表写短期延期和特殊考虑（两种用同一个表格，截止当天 23:55 前申请）。补考那条加了“挂了一门有补考吗”等问法，这类问题 RAG 摘不出安全的句子，之前会转给作者。线上要重新导入 `qa/mamo-topics.json`。
- **The RAG answer only quotes.** Tried on the live knowledge base, free models answering in their own words added steps
  no passage has ("老师会替你申请特殊考虑") and changed facts ("贴纸剩 14 天或更少时收护照" became a 14-day grace
  period), which the judge did not catch. The model now picks at most 3 sentences from the passages as `[n] sentence`;
  the code checks each one is in the passage it names (spaces ignored) and sends only those, as 「quote」[1] with the
  pages under them and a line saying they are excerpts. Each quote is widened to its whole sentence (马莫百科
  articles break lines mid-sentence), and a sentence that leans on what is around it is not sent: a list item under a
  condition, one ending in "；并且" or "：", one starting with "此流程" or a "不，" with no question in front of it. When taught Q&A or
  the Hub's FAQ answers, guide pages and articles are not mixed in. Australian campus guide pages are used only when no
  Malaysia page is quoted, and marked. The Hub links go under the sources, not between the quotes.
  When no quote can be sent, the question goes to the owner like an unsure one. The cache key includes the prompt, so answers made under the old prompt are not reused.
  / RAG 回答只摘原文：在线上知识库上试答时，免费模型用自己的话回答会补出资料里没有的步骤（“老师会替你申请特殊考虑”），也会改事实（“贴纸剩 14 天或更少时收护照”变成“过期后有 14 天宽限期”），裁判模型没发现。现在模型只能从资料里摘最多 3 句，写成 `[编号] 原句`；程序逐字核对每句是否在它标的那段资料里（忽略空格），只发核对通过的，格式是「原句」[1]，下面列出页面和说明是原文摘录。摘句按所在的整句发出（马莫百科文章会在句子中间换行）；离开上下文会看错的句子不发，比如条件下面的列表项、以“；并且”或“：”结尾的、以“此流程”或前面没有问题的“不，”开头的。已教问答或 Hub FAQ 能回答时，不混入指南页和文章。澳洲校区指南页只在没有马来西亚页面可摘时才用，并会标出来。Monash Hub 链接放在参考来源下面，不再夹在摘句中间。一句都不能发时，和“不确定”一样转给作者。缓存的键包含提示词，旧提示词下的回答不会再用。

### Added / 新增
- **Evaluation set and report.** `eval/questions.jsonl` has 50 questions: 43 the sources answer (taught Q&A asked another
  way, Monash Hub's FAQ and Malaysia guide pages), each with the links that answer it and 1–2 expected points, and 7 that
  nothing answers. `python -m wxbot eval --mode rule|rag [--model M] [--judge] [--gap S]` scores a run: retrieval hit@5, replies
  with the right link, correctness marked by a fixed judge model, unanswerable questions left alone, uncited or unsure
  RAG replies, timeouts, P50/P95 time and the share over 4 s. Runs are kept by name and the report (`docs/EVAL.md`) has
  one row per run; human labels in `eval/labels.jsonl` give the judge's agreement. CI checks the retrieval on the
  repository's own Q&A.
  / 评测集和报告：`eval/questions.jsonl` 有 50 道题，其中 43 道资料里有答案（换种问法的已教问答、Monash Hub 的 FAQ 和马来西亚校区指南页），每道带能回答它的链接和 1–2 个参考要点；另外 7 道哪里都没有答案。`python -m wxbot eval --mode rule|rag [--model M] [--judge] [--gap S]` 给一次运行打分：检索命中@5、回答带正确链接、固定裁判模型打分的正确率、不该答的没乱答、无引用或“不确定”的 RAG 回答、超时、P50/P95 耗时和超过 4 秒的比例。每次运行按名字保存，报告（`docs/EVAL.md`）每次运行一行；`eval/labels.jsonl` 里的人工标注用来算裁判的一致率。CI 用仓库自带的问答检查检索命中率。
- **Optional RAG answer** (`WXBOT_RAG=1`, off by default). When the rules find nothing or only a weak match, and the
  question names no unit or degree, the top 5 chunks go to a free OpenAI-compatible model (default Zhipu `glm-4-flash`;
  Groq works with `WXBOT_LLM_BASE` and `WXBOT_LLM_EXTRA`) with a prompt that allows only those passages, a citation after
  each claim and "这个我不确定" otherwise. Replies with no citation are dropped; when the model says it is unsure, a weak
  rule answer is withheld too and the question goes to the owner;
  good ones list the cited pages with links (two chunks of one page count once). On the 公众号 a question the rules answered waits
  only for what is left of the 4 s; timeouts and errors fall back to the rules, late calls still fill a 7-day cache.
  `ask --rag` tries it with the switch off. The introduction mentions the model only when it is on. Plain aiohttp, no SDK.
  / 可选的 RAG 回答（`WXBOT_RAG=1`，默认关闭）：规则没命中或只有弱命中、问题里也没有课程或学位代码时，把前 5 个片段发给免费的 OpenAI 兼容模型（默认智谱 `glm-4-flash`；用 `WXBOT_LLM_BASE` 和 `WXBOT_LLM_EXTRA` 也能接 Groq），提示词要求只用这些片段、每句结论标引用、没有依据就说“这个我不确定”。没有引用的回答直接丢掉；模型说不确定时，规则的弱匹配答案也不发，问题转给作者；合格的回答列出引用的页面和链接（同一页面的两个片段只列一次）。公众号上，规则已有答案的问题只等 4 秒里剩下的时间；超时和出错都退回规则的答案，晚到的调用照样写进 7 天的缓存。`ask --rag` 可以在开关关着时试用。只有打开时介绍里才提到大模型。直接用 aiohttp，不装 SDK。
- **Chunk index and hybrid search, the first step of an optional RAG mode.** `python -m wxbot index` cuts taught Q&A,
  马莫百科 articles and Monash Hub's Chinese guide pages and FAQ into passages of up to 500 characters (title in front,
  80 characters of overlap) in a new `chunk` table; `python -m wxbot search 问题` prints the top 5. Search merges the
  Q&A matcher's word overlap with a local vector model (`BAAI/bge-small-zh-v1.5` on onnxruntime, CPU only, from
  `requirements-rag.txt`) by reciprocal rank fusion, at most two passages per link. Updates are incremental: only changed
  text is embedded again and Hub pages are fetched only when they changed. Once built, `mamo-sync` and `import-qa` keep it
  current. Hub text with no Chinese is left out. Nothing answers from it yet; no language model and no cost.
  / 片段索引和混合检索，可选 RAG 模式的第一步：`python -m wxbot index` 把教过的问答、马莫百科推文、Monash Hub 的中文指南页和 FAQ 切成最多 500 字的片段（开头带标题，相邻重叠 80 字），存进新的 `chunk` 表；`python -m wxbot search 问题` 打印前 5 条。检索把问答匹配用的词语重叠和本地向量模型（onnxruntime 跑 `BAAI/bge-small-zh-v1.5`，只用 CPU，在 `requirements-rag.txt` 里）用倒数排名融合合起来，同一个链接最多两段。增量更新：只有改过的文字重新算向量，Hub 页面变了才重新取。建过一次以后，`mamo-sync` 和 `import-qa` 会顺带更新。Hub 上没有中文的内容不收。目前还没有回答用到它，不用大模型，不花钱。
- **GPA and WAM answer.** "GPA怎么算", "WAM怎么算", "绩点" and similar had only weak matches (one landed on the MPU
  answer). The new pair gives the GPA and CGPA grade values from the official GPA page, what WAM counts (NH as 45,
  WDN left out), and links the official WAM calculator.
  / 新增 GPA 和 WAM 问答：“GPA怎么算”“WAM怎么算”“绩点”之前只有弱匹配，有一个还对到了通识课。现在按官网写了 GPA 和 CGPA 的等级换算、WAM 算哪些（NH 按 45 分，WDN 不算），并附官网 WAM 计算器。
- **Manage admins from WeChat** (issue #4, the last part). `管理员 配对` gives a one-time six-digit code (10 minutes,
  void after five wrong tries); whoever sends `配对 <code>` privately to MonashGuide or the 公众号 becomes an admin and the
  owner is told. `管理员` lists the admins with numbers and `管理员 删 <number>` removes one added this way. Admins on the
  公众号 get the commands but no 待答 notes, and alerts only go to ClawBot users.
  / 在微信里管理管理员（issue #4 最后一部分）：`管理员 配对` 给出一次性的六位配对码（10 分钟有效，输错 5 次作废），私聊 MonashGuide 或给公众号发 `配对 <配对码>` 的人就成为管理员，作者会收到通知。`管理员` 列出管理员和序号，`管理员 删 <序号>` 删掉配对加入的管理员。公众号上的管理员能用命令但收不到待答通知，告警只发给 ClawBot 上的人。
- **Students' questions are no longer kept forever** (issue #10). Once a day the bot deletes logged questions, closed
  待答 questions and undelivered replies older than `WXBOT_LOG_DAYS` (90), and delivered replies older than
  `WXBOT_OUTBOX_DAYS` (30); `python -m wxbot purge` does it at once. `删除我的数据` deletes everything stored about the
  sender, and `删数据 <待答编号>` does it for an asker on the owner's side. The introduction is unchanged (the owner
  decided users need not be told). SQLite runs with `secure_delete`.
  / 同学的提问不再永久保存（issue #10）：机器人每天删除超过 `WXBOT_LOG_DAYS`（90）天的提问记录、已处理的待答和没送出的回复，以及送出超过 `WXBOT_OUTBOX_DAYS`（30）天的回复；`python -m wxbot purge` 可以立刻删一次。发「删除我的数据」删掉自己的全部记录，作者可以用 `删数据 <待答编号>` 替提问人删。介绍不变（作者决定不需要告诉用户）。SQLite 开了 `secure_delete`。
- **The bot can run away from Monash Hub** (issue #2). With `WXBOT_HUB_FILES_URL` set to the Hub repository's raw-file
  root, `mamo-sync` downloads `mamo.ts` and the two i18n files itself (whole files, replaced only when changed and only
  when they look right), and the root copy steps in `wechat-bot-mamo.service` are allowed to fail on a host without a Hub
  checkout. `docs/OPERATIONS.md` §9 has the migration plan for when the VPS expires: what moves where, j1900 with a free
  Cloudflare Tunnel or another small VPS, and the cutover order with a way back at every step.
  / 机器人可以和 Monash Hub 分开部署（issue #2）：设置 `WXBOT_HUB_FILES_URL` 为 Hub 仓库的原始文件地址前缀后，`mamo-sync` 自己下载 `mamo.ts` 和两个中文文件（整个文件下完、内容对得上、有变化才替换），`wechat-bot-mamo.service` 里 root 的复制步骤在没有 Hub 代码目录的机器上允许失败。运维手册第 9 节写了 VPS 到期时的迁移计划：每样东西搬到哪，家里的 j1900 加免费的 Cloudflare Tunnel 还是另一台小 VPS，以及每一步都能退回的切换顺序。
- **See what the matching missed** (issue #8). `未命中 [天数]` lists the questions nobody could answer in the last
  days, most asked first, each with the Q&A it almost hit (score from `WXBOT_QA_NEAR`, 0.3) and the `也问` to send,
  or "现在能答了" once it is taught; then the questions answered with "你问的是不是…". The same report arrives as
  "📊 本周小结" every Monday from 09:00 server time, only for a week that had misses.
  / 看得到没答上的问题（issue #8）：`未命中 [天数]` 列出近几天没人答上的问题，按次数排，每条附差一点命中的问答（分数从 `WXBOT_QA_NEAR`，0.3 起算）和可以直接发的 `也问`，教过了就显示"现在能答了"；后面是回了"你问的是不是…"的问题。每周一 09:00（服务器时间）以后同样的内容自动发一份"📊 本周小结"，那周没有未命中就不发。
- **Synonyms** (issue #8). `同义词 签证=visa=EMGS` makes the words one word for matching taught answers, so a Q&A
  phrased with 签证 is found by a question that says visa; the words are replaced in the text before tokenising, so
  Chinese words jieba cuts differently (学生卡) work too. `同义词` lists the groups, `同义词 删 visa` removes a word;
  stored in the database, picked up by the running bot at once. No model anywhere.
  / 同义词（issue #8）：`同义词 签证=visa=EMGS` 把这些词算成一个词，教过的问答写的是签证，同学问 visa 也能命中；替换发生在分词之前，所以 jieba 切法不同的中文词（学生卡）也能用。`同义词` 查看，`同义词 删 visa` 移除一个词；存在数据库里，运行中的机器人马上生效。依然不用模型。
- **A daily reminder for questions nobody answered** (issue #3). While any 待答 question has waited over 24 hours the
  owner gets "⏰ 有 N 个问题等了超过一天还没回复" once a day, oldest first, on the usual channels (ClawBot, or MonashGuide
  when ClawBot is down). A missed or undelivered 待答 note no longer means a student waits for weeks.
  / 没人回的问题每天提醒一次（issue #3）：有待答问题等了超过 24 小时时，作者每天收到一条"⏰ 有 N 个问题等了超过一天还没回复"，最久的在前，走平常的渠道（ClawBot，掉线时走 MonashGuide）。待答通知漏看或没送到，不会再让同学等上几周。
- **`GET /health` for an outside check** (issue #3). 200 while the owner can be reached, 503 when the ClawBot session
  expired or polling stopped for 15 minutes; counts only. `deploy/nginx-wxbot.conf` can expose it as
  `https://wxbot.secureview.tech/health` for a free uptime monitor (see OPERATIONS §1).
  / 给外部监控的 `GET /health`（issue #3）：作者能收到消息时回 200，ClawBot 登录过期或 15 分钟没轮询时回 503，只有计数。`deploy/nginx-wxbot.conf` 可以把它暴露成 `https://wxbot.secureview.tech/health`，接免费的网站监控（见运维手册第 1 节）。
- **Tests for the QR login** (issue #13, the last part). `tests/test_login.py` runs `python -m wxbot login` against a
  fake iLink server: wait → scaned_but_redirect (every later call goes to the named host) → expired (a new code is
  fetched and the PNG rewritten) → confirmed, then checks `account.json` (mode 600), the cleared update cursor and
  `session_expired` flag, the removed PNG, and that whoever scanned is the admin; plus the three ways it gives up
  (no code, incomplete credentials, timeout) and `python -m wxbot status`. The redirect host may now carry a scheme.
  / 扫码登录的测试（issue #13 最后一部分）：`tests/test_login.py` 用假的 iLink 服务器跑 `python -m wxbot login`：wait → scaned_but_redirect（之后的请求都发到指定的主机）→ expired（重新取码、重写二维码图片）→ confirmed，然后核对 `account.json`（权限 600）、清空的更新游标和 `session_expired` 标记、删掉的图片，以及扫码的人成为管理员；还有三种放弃的情况（拿不到码、凭据不全、超时）和 `python -m wxbot status`。redirect_host 现在可以带协议前缀。
- **Ask for a Handbook year** (issue #6). "FIT2102 2026", "2026版 FIT2102", "今年" or "明年" in a question picks that
  year, for the unit search by name too; the year words are not search keywords. When the unit is not in that year the
  bot reads the latest year that lists it and says which year was asked for. Every unit answer ends with the other
  years the Hub has for it and how to ask ("📅 FIT2102 还有 2026 年的 Handbook，回复「FIT2102 2026」查看").
  `WXBOT_HUB_YEAR` pins the default year (the Hub moved to 2027 in October while students still sit 2026 units).
  / 可以指定 Handbook 年份（issue #6）：问题里写"FIT2102 2026""2026版 FIT2102""今年""明年"就查那一年，按课名找课也一样；年份不会当成搜索关键词。那一年没有这门课时，退回最近收录它的年份，并说明问的是哪一年。每条课程回答末尾列出 Hub 还有哪几年的版本和怎么问（"📅 FIT2102 还有 2026 年的 Handbook，回复「FIT2102 2026」查看"）。`WXBOT_HUB_YEAR` 可以把默认年份钉住（Hub 10 月就切到 2027 了，同学还在上 2026 的课）。
- **Community posts as a source** (issue #14). Monash Hub's `/ask` already returned related community threads; the bot
  now adds up to two under the answer, solved ones first, always under the label "💬 社区里相关的讨论（学生经验，非官方）"
  with the post link. When nothing official matches but the Hub has such posts, they are the reply (with "回复「人工」"),
  instead of a forward to the owner.
  / 社区帖子作为来源（issue #14）：Monash Hub 的 `/ask` 本来就会返回相关的社区帖子，现在答案下面最多附两条，已解决的在前，固定标注"💬 社区里相关的讨论（学生经验，非官方）"并给帖子链接。官方内容都对不上但有社区帖子时，就回帖子（并提示可以回复「人工」），不再直接转给作者。

### Fixed / 修复
- Thank-yous, goodbyes and closing lines ("好的谢谢学长", "看到了", "拜拜", "没事了我去问问", 👍, [抱拳]) were
  answered as questions the bot could not answer and forwarded to the owner as 待答. They now get "不客气", "拜拜" or
  "好的" with "还有问题随时问我", are logged as `chat`, and are never forwarded. A message with anything else in it
  ("好的，学费怎么交") or a question mark is still a question.
  / 道谢、道别和结束语（“好的谢谢学长”“看到了”“拜拜”“没事了我去问问”、👍、[抱拳]）以前被当成答不上来的问题，转给作者当待答。现在回“不客气”“拜拜”或“好的”，加一句“还有问题随时问我”，日志记成 `chat`，不再转给作者。带了别的内容（“好的，学费怎么交”）或带问号的，仍然当问题处理。
- `python -m wxbot ask` never showed the "📘 Monash Hub 中文全文" line: the guide index loaded in the background and the
  command closed its connection first ("Session is closed"). It now loads the index before answering, so `ask` shows
  what users get.
  / `python -m wxbot ask` 一直不显示“📘 Monash Hub 中文全文”这一行：指南索引在后台加载，命令先关了连接（报 Session is closed）。现在先加载索引再回答，`ask` 看到的和用户收到的一样。

## 2026-10-23

### Added / 新增
- **MPU by intake for local students, and what changed in 26S2.** Two more General Studies pairs: the units
  Malaysian students take by intake (with the National Language A rule), and what changed from Semester 2, 2026
  (4 units to 6, for both international and local students). The first pair also matches "26S2入学要修哪些MPU",
  unit codes like "MPU3172是什么", and tells students from intakes the page doesn't list (2025 S2, 2026 S1) to ask
  Monash Malaysia Connect, as the official page says. The 选课 answer no longer lists only international students'
  units. "MPU算WAM吗" is now "MPU计入WAM吗" so "WAM怎么算" goes to the Hub FAQ.
  / 通识课再加两组：马来西亚本地学生按入学学期要修哪些 MPU（含 National Language A 的条件），以及 2026 年第 2 学期入学起改了什么（国际生和本地生都从 4 门变 6 门）。原来那组也能回答“26S2入学要修哪些MPU”和“MPU3172是什么”这类问法；官网没列的入学学期（2025 年第 2 学期、2026 年第 1 学期）按官网说的让同学问 Monash Malaysia Connect 确认。选课那条不再只列国际生的课。“MPU算WAM吗”改成“MPU计入WAM吗”，“WAM怎么算”交给 Hub 的 FAQ。
- **Hurdle answers** for the rules that apply from 27 July 2026: what a hurdle is, that threshold hurdles are gone by
  31 December 2026, that a failed competency hurdle gets at least one additional assessment, and what NH, NGO and
  supplementary mean after a fail, including how NH counts in GPA and WAM. A third pair answers plain "挂科了怎么办"
  with the supplementary rules (45 to 49, NS, 90 days, a pass is 50). Each pair has 19 to 31 phrasings, including
  how parents and students ask in a hurry ("孩子成绩显示NH", "总分够了为什么还挂", "补考怎么申请"). Written in
  Chinese from the Assessment Regime Procedure, the student supplementary page and the Malaysia results FAQ.
  / hurdle 新规问答（2026 年 7 月 27 日起的学期适用）：什么是 hurdle，threshold hurdle 到 2026 年 12 月 31 日全部取消，competency hurdle 没过至少再给一次额外考核，以及没过后的 NH、NGO、supplementary 补考，NH 怎么算进 GPA 和 WAM。另加一组回答普通的“挂科了怎么办”（45 到 49 分、NS、90 天内、过了记 50 分）。每组 19 到 31 个问法，包括家长和同学随口的问法（“孩子成绩显示NH”“总分够了为什么还挂”“补考怎么申请”）。根据 Assessment Regime Procedure、学生版补考页面和马莫成绩 FAQ 用中文写。
- **`import-qa` adds new phrasings to pairs already there.** Before, a pair that was already imported was skipped
  whole, so phrasings added to the file later never went live. The Moodle pair now also answers "Moodle打不开"
  and "Moodle挂了", which used to land on the hurdle answer.
  / `import-qa` 会给已有的问答补上新问法：之前已导入的问答整条跳过，文件里后加的问法上不了线。Moodle 那条现在也能回答“Moodle打不开”“Moodle挂了”，之前会对到 hurdle 的答案。
- **`import-qa --replace`** gives a pair with the same first phrasing the file's new answer, keeping its number and
  hits, so an edited answer no longer has to be deleted before importing.
  / `import-qa --replace`：第一个问法相同的问答换成文件里的新答案，编号和命中次数不变，改了答案不用再先删掉。
- **`不问 编号 问法`** removes one phrasing from a Q&A (not the first). Used to take "GPA怎么算" and "WAM怎么算" back
  off the Moodle pair: they belong to the Monash Hub FAQ, which explains the calculation.
  / 新命令 `不问 编号 问法`：去掉问答的一种问法（第一种不能去）。用它把“GPA怎么算”“WAM怎么算”从 Moodle 那条去掉了，这两个问题该由 Monash Hub 的 FAQ 回答，那里讲了怎么算。
- **General Studies, transport, campus map and M-Pass answers** in `qa/mamo-topics.json`, written in Chinese from
  monash.edu.my: which MPU units international students take by intake (General Studies / 通识课 / MPU all match),
  the campus address and how to get there from the airport, BRT and the free Sunway shuttle, the Monash Study app for
  finding rooms, and how to apply for or replace an M-Pass. Each links the official page. Importing the file again
  adds only the 4 new pairs.
  / `qa/mamo-topics.json` 新增通识课、交通、校园地图和 M-Pass 学生卡问答，根据马莫官网用中文写：国际学生按入学学期要修哪些 MPU 课（问 General Studies、通识课、MPU 都能答到），学校地址和从机场怎么来、BRT 和 Sunway 免费穿梭巴士，找教室用 Monash Study app，M-Pass 怎么申请和补办。每条附官网链接。再导入一次只会加这 4 条新的。

### Fixed / 修复
- **Parents' questions missed.** "您好，请问孩子怎么交学费" scored low because 您好, 孩子 and 家长 counted as topic
  words. They are stopwords now, so a parent's question matches like the student's.
  / 家长的问法匹配不上：“您好，请问孩子怎么交学费”里的您好、孩子、家长被当成了关键词，分数被拉低。现在这些词不计入匹配，家长问和学生问效果一样。
- **"你好在吗" went to the owner as a question.** Only a single greeting got the introduction; two greetings or
  "老师您好，请问" were forwarded. Any message made only of greetings now gets the introduction.
  / “你好在吗”会被当成问题转给作者：之前只有单个问候语才回自我介绍，两个连着说或者“老师您好，请问”都会转人工。现在只有问候语的消息都回自我介绍。
- The introduction lists questions for new students and parents (怎么报到 / 学费怎么交 / 从机场怎么去学校).
  / 自我介绍里加了新生和家长常问的例子。
- Removed `deploy-check.txt`, a one-off test log that was merged from a temporary branch.
  / 删掉了从临时分支合并进来的一次性测试记录 `deploy-check.txt`。

## 2026-10-22

### Added / 新增
- **Answers written from the 马莫百科 posts.** `qa/mamo-topics.json` has 12 Q&A pairs for what students ask most:
  选课 (WES), 缴费, Moodle, 交作业, 报到, 选上课时间 (Allocate), 交换, 入台证, 续签, 出勤, 毕业 and the common
  sites. Each answer has the key steps and official links from the post, and links the post itself. The owner imports
  it with `import-qa` after reading it (see OPERATIONS).
  / 根据马莫百科推文写的问答：`qa/mamo-topics.json` 有 12 组，覆盖同学最常问的选课（WES）、缴费、Moodle、交作业、报到、选上课时间（Allocate）、交换、入台证、续签、出勤、毕业和常用网站。每条答案写了推文里的关键步骤和官方链接，并附上推文链接。作者看过后用 `import-qa` 导入（见运维手册）。
- **Unanswered questions point to the 马莫百科 archive.** The "已转给作者" reply now also links
  https://monashhub.secureview.tech/mamo, which lists every post by topic.
  / 答不上来时附上马莫百科往期文章：回复"已转给作者"时，同时给出 Monash Hub 上按主题整理的全部推文 https://monashhub.secureview.tech/mamo 。

### Fixed / 修复
- **The server commands in OPERATIONS failed with "No module named wxbot".** They ran from the ssh login folder,
  and `wxbot` is only found from `/opt/wechat-bot`. Each command now starts with `cd /opt/wechat-bot`.
  / 运维手册里的服务器命令会报 "No module named wxbot"：它们在 ssh 登录后的目录里运行，而 `wxbot` 只有在 `/opt/wechat-bot` 里才找得到。现在每条命令前都加了 `cd /opt/wechat-bot`。
- **"怎么选课", "学费怎么交" and "Moodle怎么用" found no article** when only a post's title and summary were indexed
  (the body fetch fails sometimes). Students type Moodle, Allocate and 学费 where the posts say 学习平台, 课表系统 and
  缴费, single characters like 选 and 交 diluted the score, and jieba cut 报到 into 报 + 到. Article matching now maps
  those words, ignores one-character words, and lets one matched word count when it is what the post's title is about
  (generic words like 学生 or 指南 never do).
  / 只收录了标题和摘要的文章（正文偶尔抓不到）匹配不上"怎么选课""学费怎么交""Moodle怎么用"：同学打的是 Moodle、Allocate、学费，推文写的是学习平台、课表系统、缴费；"选""交"这种单字拉低了分数；jieba 还把"报到"切成了"报"和"到"。现在文章匹配会换成推文里的说法，忽略单字，标题讲的就是这个词时一个词也能命中（学生、指南这类泛词不算）。
- **"怎么申请宿舍" looked like "怎么申请交换".** Bigrams were taken across stopwords, so 怎么申请 left 么申 behind and
  two unrelated questions shared it. Multi-character stopwords now split the text before bigrams are taken.
  / "怎么申请宿舍"和"怎么申请交换"被当成很像：二字组跨过了停用词，"怎么申请"会多出一个"么申"。现在先按多字停用词切开再取二字组。

## 2026-10-11

### Fixed / 修复
- **A single failed ClawBot poll sent an alert.** iLink's CDN answers a long poll with HTTP 522 every hour or two, the retry
  two seconds later works, and the owner still got "ClawBot 收消息出错了". Poll errors are now logged at INFO and only the
  third failure in a row is an alert.
  / ClawBot 偶尔一次收消息失败也会推送提醒：iLink 的 CDN 每隔一两个小时会有一次轮询返回 HTTP 522，两秒后重试就好了，但作者还是会收到"ClawBot 收消息出错了"。现在单次失败只写普通日志，连续 3 次失败才提醒。
- **One slow Monash Hub call was reported as "连不上 Monash Hub".** A unit search that runs out of the 公众号 reply budget
  times out even when the Hub is up, and a timeout's message is empty, so the alert ended in "failed:" with no reason.
  A timeout is now an alert only after three in a row with no Hub answer in between (a refused connection still alerts at
  once), and the log line names the error and the time allowed.
  / Monash Hub 偶尔一次响应慢也会提醒"连不上 Monash Hub"：公众号回复的时间快用完时，课程搜索即使 Hub 正常也会超时，而且超时的报错内容是空的，提醒末尾只有"failed:"。现在超时要连续 3 次（中间 Hub 没有正常回过）才提醒，连接被拒绝仍然立刻提醒；日志里会写明是什么错误、给了多少秒。
- **MonashGuide could be logged out for days without anyone knowing.** The bot only checked the account's login when it
  started, and while waiting logged at INFO level, which never alerts. After the PC WeChat in `wxbot-wechat` lost its login,
  group @s went unanswered and the owner found out from the silence. `pcwx.watch` now checks every 10 minutes for as long as
  the bot runs, registers the callback again when the account is back, and after 10 minutes away sends a ClawBot alert
  (repeated every 6 hours) with the re-login steps.
  / MonashGuide 小号掉线可能好几天都没人知道：之前只在启动时检查一次登录，等待时只写普通日志，不会触发提醒。这次 `wxbot-wechat` 里的 PC 微信掉线后，群里 @ 都没有回复，是靠群里没反应才发现的。现在 `pcwx.watch` 在机器人运行期间每 10 分钟检查一次，小号重新登录后自动重新注册回调；掉线超过 10 分钟就给 ClawBot 推送提醒（每 6 小时重复一次），提醒里写了重新登录的步骤。

## 2026-10-09

### Fixed / 修复
- **Monash Hub outages were reported as "程序报了一个错误".** The alert pattern looked for `hub /ask`, but `hub._call` logs
  `hub POST /ask failed` and `hub GET /units/... failed`, so it never matched, and every path and error became its own
  alert kind. All Hub call failures are now one kind with the plain "连不上 Monash Hub" text. Failed sends and an expired
  iLink session have their own plain text too; the expired-session reminder repeats every 6 hours instead of 30 minutes.
  / Monash Hub 连不上时，告警之前只显示"程序报了一个错误"，而且不同接口各算一类，可能连发好几条。现在所有 Hub 调用失败合成一类，显示"连不上 Monash Hub"。消息发送失败和 ClawBot 登录过期也有了中文说明，登录过期每 6 小时提醒一次。
- Background tasks (handling each message, forwarding notes, sending alerts, attaching to MonashGuide) were started without
  keeping a reference, which lets Python garbage-collect them before they finish. They now go through `tasks.spawn`.
  / 后台任务之前没有保留引用，Python 可能在任务跑完前把它回收掉，现在统一用 `tasks.spawn` 启动。
- 「答 N ...」 for a question that was already answered added a second Q&A with the same question; it now corrects the
  existing one (and still sends the new answer to the asker).
  / 对已经答过的待答再发「答 N …」会多出一组重复的问答，现在改为更新原来那组，新答案照样发给提问人。
- The "N 答案" shortcut took "3门课都挂了怎么办" as an answer to 待答 #3. It now needs a space after the number.
  / 「编号 答案」快捷回复之前会把"3门课都挂了怎么办"当成对 #3 的回答，现在编号后面必须有空格。
- Missing Monash Hub i18n files at start-up were never logged, so the "读不到中文词典" alert could not fire.
  / 启动时就缺少 Monash Hub 中文词典文件的情况之前不会记日志，对应的告警也就发不出来。
- `mamo-sync-api` blocked the event loop with `time.sleep`; `/health` used a plain function (deprecated in aiohttp).
  / `mamo-sync-api` 里的 `time.sleep` 会卡住事件循环；`/health` 改成 async 处理函数。

### Added / 新增
- **Nightly backup** (issue #1): `python -m wxbot backup` writes a consistent copy of `kb.sqlite` (SQLite online backup) to
  `data/backups/` and keeps the newest 14; `wechat-bot-backup.timer` runs it at 03:30. `export-qa` / `import-qa` move the
  taught answers on their own, with no user data. The off-site copy is still to be set up on the server.
  / 每晚备份知识库：`python -m wxbot backup` 把 `kb.sqlite` 的一致副本写到 `data/backups/`，保留 14 份，由 `wechat-bot-backup.timer` 每天 03:30 运行。`export-qa` / `import-qa` 单独导出、导入教过的问答，不含用户数据。异地备份还需要在服务器上配置。
- **Stale outbox replies expire** (issue #5): a queued 公众号 reply older than `WXBOT_OUTBOX_DAYS` (30) is no longer
  shown and is counted in `统计`; one older than 3 days says which day it was written. `待答` shows how long each
  question has waited and flags those over 3 days with ⏰.
  / 待发回复超过 30 天不再显示，`统计` 里会列出条数；超过 3 天的回复会注明日期。`待答` 显示每个问题等了多久，超过 3 天加 ⏰。
- **`列表 [页码]`** (issue #4, part): every Q&A with its first phrasing and hit count, 20 per page.
  / 新命令 `列表`：分页列出所有问答和命中次数。
- **CI** (issue #12): GitHub Actions runs `ruff check --select E9,F` and the tests on every push to `main` and every pull request.
  / 加了 GitHub Actions：每次推送和 PR 都跑 ruff 基本检查和全部测试。
- **Tests for the iLink client, the ClawBot loop and the 马莫百科 sync** (issue #13, except the QR login): 524 as an empty
  poll, the tokenless retry, session expiry, dedupe and group handling in `Bot.process`, the update cursor only moving on a
  good poll, and `mamo.sync_from_hub`.
  / 补了 iLink 客户端、ClawBot 收消息循环和马莫百科同步的测试（扫码登录还没测）。
- **Alerts reach the owner when ClawBot is down** (issue #3, partly). With `WXBOT_OWNER_WXID` and MonashGuide set up, an
  alert that ClawBot cannot deliver (expired login, no iLink login) goes to the owner's own WeChat through MonashGuide.
  / ClawBot 掉线时告警改走 MonashGuide 发到作者自己的微信（需要配置 `WXBOT_OWNER_WXID` 和 MonashGuide）。

### Changed / 改动
- Docs: the READMEs describe the MonashGuide group-chat channel and its settings (they still said group chats were not
  possible), carry badges, and the Chinese docs are no longer hard-wrapped (GitHub showed a space at every line break).
  / 文档：README 补上 MonashGuide 群聊通道和相关配置（之前还写着群聊做不到），加了徽章；中文文档去掉手动换行（GitHub 会在换行处显示多余空格）。
- A unit answer reads each year's unit page from Monash Hub once instead of up to three times, which leaves more of the
  4-second 公众号 budget for the answer. SQLite indexes for the outbox, pending questions, the log and phrasings.
  / 一个课程问题对同一年的课程页只请求一次 Monash Hub（之前最多三次），给公众号 4 秒的时限留出余量；给待发、待答、日志和问法表加了索引。

## 2026-10-04

### Changed / 改动
- **Every reply links to Monash Hub.** Official pages each get their Chinese summary as well as the link. An FAQ answer links
  the Hub guide page it comes from (`page_slug`, added to Monash Hub's `/ask` the same day). Taught answers, articles and
  anything else without a Hub page of its own get a link to the Hub's search for the question. Matching official pages are
  shown under the 马莫百科 articles too, instead of being dropped. The introduction, the short 关注语 introduction and the
  "答不上来" reply carry the Hub link.
- **Every official link goes out with its Monash Hub page.** The bot reads the Hub's list of indexed official pages
  (`/guides`, 762 pages) in the background every 6 hours, and under any line with an official link (a taught answer, the
  owner's 「答」 reply, an FAQ's source) adds "📘 Monash Hub 中文全文" for the same page.
  / 每条回复都带 Monash Hub 链接：官方页面每条都有中文摘要和中文全文链接；FAQ 链到 Hub 上对应的指南页；人工教的问答、公众号文章等没有 Hub 页面的回答附 Hub 搜索链接；匹配到文章时也一起列出 Hub 上的官方页面；自我介绍、关注语和转人工的回复也加了 Hub 链接。
  / 回复里只要有官网链接（人工教的问答、Waldo 的人工回复、FAQ 原文），下面就附上 Hub 上同一页的中文全文链接。

### Fixed / 修复
- Official pages after the first had only the English link, although Monash Hub has a Chinese page for each. Every page in the
  list now gets its "📘 中文全文" link; the summary is still only on the first.
  / 官方页面列表里第 2、3 条之前只有官网英文链接，现在每条都附 Monash Hub 中文全文链接，摘要仍只给第一条。
- **"你能干什么" was forwarded to the owner.** Questions about the bot itself ("你会什么", "你是什么大模型", "能问什么",
  "你是真人吗") now get the introduction; in a group it says to @ the bot. The introduction lists units, degrees and
  policies, says it is not a chat model, and no longer uses FIT2004 (dropped from 2027) as the example.
  / 问机器人本身（"你能干什么""你是什么大模型"等）不再转人工，直接回自我介绍；群里会说明要 @ 它。介绍里不再拿已停开的 FIT2004 举例。
- Page titles from Monash Hub now carry the campus, so "（马来西亚校区）（马来西亚校区）" was doubled; and navigation crumbs
  ("• Handbook • 团队领导 …") were shown as a summary.
  / Hub 标题已自带校区，机器人又加了一遍；导航碎片被当成摘要显示。均已修复。
- Official pages keep Monash Hub's relevance order (only Australia-only pages move last); ranking every Malaysia page first put a
  pharmacy page above "internal course transfer" for 转专业.
  / 官方页面保留 Hub 的相关度顺序，只把澳洲专用页面放后面。
- Removed four taught answers (GPA / 绩点 / WAM / 平均分, 2026-09-27) that were copies of an old Hub reply and hid the Hub's
  current FAQ answers; backed up on the server first.
  / 删除了 4 条测试时存下的旧 Hub 回复（GPA、绩点、WAM、平均分），它们挡住了 Hub 现在更准确的 FAQ；删除前已在服务器上备份。

### Added / 新增
- **Faculty teach-out notices** (Monash Hub #143): unit answers show "📌 学院通知：这门课有变动" with the faculty's wording
  ("No longer offered - Replace with FIT3234") and its link.
  / 课程答案显示学院的停开/替代通知（原文照录，附链接）。
- **Areas of study by code** ("MMEDCHEM01介绍"): type, credit points, structure with unit codes and names, links.
  / 支持按专业方向代码查询（如 MMEDCHEM01），显示类型、学分、结构和课程。

## 2026-10-02 (4)

### Changed / 修改
- Article answers say "“马莫百科”公众号相关文章" (the group bot is itself called 马莫百科, so "马莫百科相关文章" read as its own).
  / 文章类回答改称「“马莫百科”公众号相关文章」，避免和机器人自己的昵称混淆。
- **The owner is asked where the question was asked.** With `WXBOT_OWNER_WXID` set: a group question the bot cannot answer
  @-s the asker and the owner in that group (every time); when the owner replies in the group @-ing the asker, the reply is
  learned as the answer. 公众号 and private-chat misses go to the owner's own WeChat through MonashGuide, where he can use
  「答」 and the other admin commands; ClawBot keeps only the alerts. If he is not in the group, he gets a private note.
  / 群里答不上来的问题直接在群里 @ 提问人和 Waldo；Waldo 在群里 @ 提问人回答后自动记进知识库。公众号和私聊答不上来的，由 MonashGuide 私聊发给 Waldo 的微信，在那里直接「答 编号」；ClawBot 只用来收告警。Waldo 不在群里时改为私聊通知。
- Group replies @ the asker by their WeChat nickname (was "@同学"); a hand-typed "@马莫百科" counts as a mention.
  / 群里回复用提问人的微信昵称 @ 对方；手打的「@马莫百科」也算 @ 机器人。

## 2026-10-02 (3)

### Added / 新增
- **Group chats through the MonashGuide personal account** (`wxbot/pcwx.py`): students @ it in a WeChat group or message it
  privately; it answers like the 公众号 and @-s the asker. Runs on the unofficial jwping/wxbot (PC WeChat in Docker) with a
  separate account; only @-mentions and private messages are read. Forwarded questions answered with 「答」 go back to the group.
  Owner's decision (2026-10-02), replacing the "tracking only" position of #15.
  / 通过 MonashGuide 个人号支持微信群：同学在群里 @ 它或私聊提问，机器人回答并 @ 提问人。基于非官方的 jwping/wxbot，用单独的小号；只读 @ 它的消息和私聊。转人工的问题回答后发回原群。

## 2026-10-02 (2)

### Added / 新增
- **Degrees**: a degree code (C2001) or name ("计算机科学学士要修多少学分") gets a degree card from `/courses`: type,
  credit points, years, campuses (Malaysia first), majors/minors, structure, with the Handbook and Monash Hub links. A degree
  the default year dropped is read from the year before, and the card says so.
  / 学位：问学位代码或学位名，回复学位卡片（学分、年限、校区、专业方向、辅修、课程结构，附官网和 Monash Hub 链接）。
- **Units by name** (#7): "编程范式有期末考试吗" finds FIT2102 by title and answers as if the code was given; an ambiguous
  name ("算法课") lists the matching units and asks for the code.
  / 按课名找课：能直接按课名回答；课名有歧义时列出候选课程，请对方回复课程代码。
- Official page lists put Monash Malaysia and all-campus pages before Australia-only ones, show the top page's summary and its
  Chinese full text on Monash Hub, and offer the Hub's related questions.
  / 官方页面列表把马来西亚校区和全校通用的页面排在澳洲专用页面前面，第一条附中文摘要和 Monash Hub 中文全文链接，并给出相关问题。

### Fixed / 修复
- A question about learning outcomes (`handbook_outcomes`) was treated as unanswered and forwarded to the owner.
  / 问学习目标时被当成答不上来、转了人工。
- Monash Hub being down no longer forwards questions to the owner (#9); the asker is told to try again in a few minutes.
  / Monash Hub 暂时连不上时不再转人工，只提示稍后再问。
- All Hub calls for one question share a 3.4 s budget, so a 公众号 reply is not cut off at WeChat's 5 s.
  / 一个问题的所有 Hub 请求共用 3.4 秒总时限，公众号不再超时。
- A 公众号 answer that took longer than 4 s was lost, together with any queued reply from the owner; it now waits in the
  outbox and is shown when the user sends anything (e.g. "1").
  / 公众号超过 4 秒才算完的答案（连同排队的人工回复）会丢；现在放进待发，用户随便发一条就能看到。
- "Nov 2026" / "Sem 2026" are no longer read as unit codes (which made the bot skip a taught Q&A).
  / "Nov 2026"、"Sem 2026" 不再被当成课程代码。
- The ClawBot admin chat no longer drops a repeated message for 5 minutes (only for 15 s, against redelivery).
  / ClawBot 管理后台重复发同一句话不再被吞 5 分钟（只在 15 秒内去重）。

## 2026-10-02

### Changed / 修改
- **"FIT2102学什么" now answers with the unit itself**: summary, learning outcomes, assessment, offerings, prerequisites,
  then the Handbook and Monash Hub links (≤ 1500 bytes), instead of only a link. Monash Hub's `/ask` returns a bare
  link block for a unit code with no intent keyword; the bot now fetches `/units/{code}?locale=zh`.
  / "FIT2102学什么"这类问题现在直接回答课程简介、学习目标、考核方式、开课安排和先修，最后才是官网链接，不再只给链接。
- **Falls back to the latest Handbook year that lists the unit** when the default year dropped it (FIT2004 and others are
  not in 2027), and says so; units in no year get "找不到，请检查课程代码" instead of being forwarded to the owner.
  / 默认年份的 Handbook 里没有这门课时，退回最近收录它的年份并说明；所有年份都没有的课提示检查课程代码。
- Workload text uses the website's Chinese instead of the English paragraph from `/ask`.
  / 工作量说明改用网站里的中文，不再贴英文长段落。

## 2026-09-27: first working version / 第一个可用版本

### Added / 新增
- **iLink (ClawBot) channel** with QR login, long-polling and send; used as the owner's admin console.
  / iLink（ClawBot）通道：扫码登录、长轮询、发送，作为作者的管理后台。
- **马莫百科 公众号 front door**: plaintext developer-mode callback at `wxbot.secureview.tech/mp`, signature check,
  retry de-duplication, passive replies within WeChat's 5 s / 2048-byte limits, an outbox for answers that arrive later.
  / 马莫百科公众号作为对外入口：明文模式回调、验签、重试去重、5 秒 / 2048 字节限制内的被动回复、迟到答案的待发队列。
- **Model-free answering**: taught Q&A (jieba words + CJK bigrams, IDF overlap), Monash Hub `/ask`, 马莫百科 articles
  (indexed from Monash Hub's post list every 6 h, or added by link).
  / 不用大模型的回答：教过的问答、Monash Hub、马莫百科文章（每 6 小时从 Monash Hub 的文章列表收录，或发链接收录）。
- **Owner commands** in WeChat: 教 / 也问 / 改 / 删 / 看 / 查 / 试 / 待答 / 答 / 忽略 / 收录 / 删文 / 关注语 / 统计.
  Answers can be given as `答 N …`, `N …`, or by quoting the "待答" note.
  / 作者的微信命令；回答待答问题可用 `答 N …`、`N …`，或引用待答通知。
- **Forward-to-owner flow**: unanswered questions become "待答 #N", the answer goes back to the asker and becomes a Q&A.
  / 转人工流程：答不上来的问题变成待答，回答发给提问人并记成问答。
- **Chinese answers from Monash Hub's own strings** (`?locale=zh`, `frontend/i18n` copies), official-link footer on every
  answer, machine-translation labels, an Australia-campus warning, English Handbook prose never pasted.
  / 用 Monash Hub 自己的中文回答，每条附官网链接，机器翻译会注明，澳洲校区页面有提示，不贴英文长段落。
- **Welcome (关注语)** on follow, on greetings, and before the answer to a new follower's first message; compacted
  when the answer needs the room. Editable with `关注语`.
  / 关注语：关注时、打招呼时、新用户第一条提问时先发；答案太长时自动精简。
- **Alerts to the owner's ClawBot chat** for slow replies, hub/iLink failures and handler errors, once per kind per 30 min.
  / 出问题时推送到作者的 ClawBot，同类问题 30 分钟内只提醒一次。
- Deployment: systemd units, nginx site, `install.sh`, `push.sh`; tests with a fake Monash Hub and fake 公众号 requests.
  / 部署：systemd 单元、nginx 站点、安装和推送脚本；带模拟 Monash Hub 和模拟公众号请求的测试。

### Fixed / 修复
- iLink on the international host answers long polls with HTTP 524 after ~15 s; treated as an empty poll.
  / 国际节点 15 秒后返回 524，按空轮询处理。
- Unit codes glued to Chinese ("FIT2004有期末考试吗") were missed by Monash Hub's `\b` regex; worked around in the bot,
  then fixed in Monash Hub itself and the workaround removed.
  / 课程代码紧贴中文时 Monash Hub 识别不出：先在机器人侧绕过，Monash Hub 修好后删除了绕过代码。
- A unit question is no longer taken by a taught Q&A that names no unit.
  / 课程问题不再被没提到该课程的教过问答截走。
- Match index is rebuilt when another process (CLI, sync timer) changes the database.
  / 其他进程修改数据库后，匹配索引会自动重建，不用重启。
- Commands accepted without a space before the id (`答1 …`).
  / `答1 …` 这种紧贴编号的写法也能识别。
