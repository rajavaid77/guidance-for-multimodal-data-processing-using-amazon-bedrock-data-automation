import sys, html
cells=[]; n=[0]
def nid():
    n[0]+=1; return f"n{n[0]}"
PTS="points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],[0,0.25,0],[0,0.5,0],[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]];"
def v(label,style,x,y,w,h,id=None):
    id=id or nid()
    cells.append(f'<mxCell id="{id}" value="{html.escape(label)}" style="{style}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    return id
def icon(label,name,color,x,y,s=60):
    return v(label,f"sketch=0;{PTS}outlineConnect=0;fontColor=#232F3E;fillColor={color};strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{name};",x,y,s,s)
def lam(label,x,y):
    return v(label,"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=#ED7100;strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.lambda_function;",x,y,48,48)
def user(label,x,y):
    return v(label,"sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;fillColor=#232F3D;strokeColor=none;dashed=0;verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=12;fontStyle=1;aspect=fixed;pointerEvents=1;shape=mxgraph.aws4.user;",x,y,50,50)
def awsgroup(label,gr,stroke,font,x,y,w,h,dashed=0):
    return v(label,f"points=[];outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=13;fontStyle=1;container=0;pointerEvents=0;collapsible=0;recursiveResize=0;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr};strokeColor={stroke};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor={font};dashed={dashed};",x,y,w,h)
def box(label,x,y,w,h,stroke="#879196",fill="none",dashed=1,bold=1,size=12):
    return v(label,f"rounded=1;arcSize=4;html=1;whiteSpace=wrap;dashed={dashed};fillColor={fill};strokeColor={stroke};verticalAlign=top;align=left;spacingLeft=10;spacingTop=4;fontColor=#232F3E;fontStyle={bold};fontSize={size};",x,y,w,h)
def comp(label,x,y,w,h,fill="#E6F6F3",stroke="#01A88D",bold=0):
    return v(label,f"rounded=1;arcSize=12;html=1;whiteSpace=wrap;fillColor={fill};strokeColor={stroke};strokeWidth=1.5;fontColor=#232F3E;fontSize=11;fontStyle={bold};align=center;verticalAlign=middle;",x,y,w,h)
def e(s,t,label="",style="",pts=None):
    p=""
    if pts: p='<Array as="points">'+"".join(f'<mxPoint x="{a}" y="{b}"/>' for a,b in pts)+'</Array>'
    cells.append(f'<mxCell id="{nid()}" value="{html.escape(label)}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#545B64;strokeWidth=1.5;fontSize=11;fontColor=#232F3E;labelBackgroundColor=#ffffff;{style}" edge="1" parent="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry">{p}</mxGeometry></mxCell>')

# ---- groups (drawn first = behind)
awsgroup("AWS Cloud","group_aws_cloud_alt","#232F3E","#232F3E",140,20,1560,1010)
awsgroup("AWS Region","group_region","#00A4A6","#147EBA",160,50,1520,965,dashed=1)
box("Intake",190,90,420,260)
box("Orchestration",640,90,190,160)
box("Document Understanding",330,400,480,180)
box("Human-in-the-Loop Review",330,630,480,250)
agc=box("Amazon Bedrock AgentCore",900,90,520,560,stroke="#01A88D",fill="#F2FBF9",dashed=0,size=13);cells[-1]=cells[-1].replace("spacingLeft=10","spacingLeft=40")
icon("","bedrock","#01A88D",908,96,30)
rt=box("AgentCore Runtime  |  Strands Agents",920,150,270,480,stroke="#01A88D",fill="#FFFFFF",dashed=1,size=11)
box("Amazon Bedrock",1445,90,220,330)
box("Data",1445,450,220,400)
tools=box("Gateway Targets (AWS Lambda)",900,680,520,160)
box("Security & Observability",900,870,765,135)

# ---- users
prov=user("Medical Provider",40,150)
exm=user("Claims Examiner",40,820)

# ---- intake / orchestration
pp=icon("AWS Amplify<br>Provider Portal","amplify","#DD344C",210,130)
apigw=icon("Amazon<br>API Gateway","api_gateway","#E7157B",320,130)
cog=icon("Amazon Cognito<br>Provider + examiner pools","cognito","#DD344C",320,240)
s3in=icon("Amazon S3<br>Claim packets","s3","#7AA116",430,130)
eb=icon("Amazon<br>EventBridge","eventbridge","#E7157B",540,130)
sfn=icon("AWS Step Functions<br>Claim workflow","step_functions","#E7157B",705,160);cells[-1]=cells[-1].replace("verticalLabelPosition=bottom;verticalAlign=top","verticalLabelPosition=top;verticalAlign=bottom")

# ---- document understanding
s3out=icon("Amazon S3<br>BDA output (JSON)","s3","#7AA116",400,450)
bda=icon("Amazon Bedrock Data Automation<br>Split, classify, extract<br>CMS-1500 + evidence blueprints","bedrock","#01A88D",600,450)

# ---- human review
sns=icon("Amazon SNS","sns","#E7157B",540,660)
amp=icon("AWS Amplify<br>Examiner UI","amplify","#DD344C",380,760)
apigw2=icon("Amazon API Gateway","api_gateway","#E7157B",540,760)
lrev=icon("AWS Lambda<br>Review API","lambda","#ED7100",705,760)

# ---- agents
sup=comp("<b>Supervisor Agent</b><br>Plans review, merges findings",950,185,210,50,fill="#01A88D",stroke="#01786A")
cells[-1]=cells[-1].replace("fontColor=#232F3E","fontColor=#FFFFFF")
val=comp("<b>Validation Agent</b><br>Fields, formats, codes, duplicates",970,262,200,44)
cli=comp("<b>Clinical Review Agent</b><br>Claim vs evidence, medical necessity",970,320,200,44)
eli=comp("<b>Eligibility Agent</b><br>Coverage on DOS, COB",970,378,200,44)
adj=comp("<b>Adjudication Agent</b><br>Decision, CARC/RARC, rationale",970,436,200,44)
v("Strands Agents SDK<br>Python container<br>1 session per claim","text;html=1;align=center;verticalAlign=middle;fontSize=10;fontColor=#545B64;fontStyle=2;",970,520,200,60)

obs=comp("<b>AgentCore Observability</b><br>OTEL traces to CloudWatch",1220,165,180,50)
mem=comp("<b>AgentCore Memory</b><br>Claim session context",1220,248,180,50)
idn=comp("<b>AgentCore Identity</b><br>Inbound IAM, outbound OAuth",1220,392,180,50)
gw=comp("<b>AgentCore Gateway</b><br>Lambda targets as MCP tools",1220,478,180,56,fill="#01A88D",stroke="#01786A")
cells[-1]=cells[-1].replace("fontColor=#232F3E","fontColor=#FFFFFF")

# ---- bedrock
fm=icon("Foundation Models<br>Claude","bedrock","#01A88D",1480,130)
grd=icon("Guardrails<br>PHI, grounding","bedrock","#01A88D",1595,130)
kb=icon("Bedrock Knowledge Bases<br>Policies, EoC, LCD/NCD","bedrock","#01A88D",1530,312)

# ---- data
s3kb=icon("Amazon S3<br>Policy documents","s3","#7AA116",1475,520)
aoss=icon("Amazon S3 Vectors<br>Policy embeddings","s3","#7AA116",1595,520)
aur=icon("Amazon Aurora PostgreSQL<br>Members, plans, claims,<br>decisions, code sets","aurora","#C925D1",1535,700)

# ---- tool lambdas
t1=lam("validate_codes",950,725); t2=lam("check_eligibility",1070,725)
t3=lam("find_duplicates",1190,725); t4=lam("save_decision",1310,725)

# ---- security & ops
icon("AWS KMS","key_management_service","#DD344C",950,895,48)
icon("AWS Secrets Manager","secrets_manager","#DD344C",1080,895,48)
icon("Amazon CloudWatch","cloudwatch_2","#E7157B",1210,895,48)
icon("AWS X-Ray","xray","#ED7100",1340,895,48)
icon("AWS CloudTrail","cloudtrail","#E7157B",1470,895,48)
v("VPC isolated subnets, no NAT<br>HIPAA-eligible services, BAA","text;html=1;whiteSpace=wrap;align=left;verticalAlign=middle;fontSize=11;fontColor=#545B64;",1540,890,130,60)

# ---- edges
e(prov,pp,"1 Upload")
e(pp,apigw)
e(pp,cog,"Sign-in","dashed=1;exitX=0.5;exitY=1;entryX=0;entryY=0.5;")
e(cog,apigw,"","endArrow=none;dashed=1;")
e(apigw,s3in)
e(s3in,eb,"2")
e(eb,sfn)
e(sfn,bda,"3 Invoke BDA async","exitX=0.25;exitY=1;entryX=0.5;entryY=0;")
e(bda,s3out)
e(s3out,eb,"4 Job complete","dashed=1;exitX=0.5;exitY=0;entryX=0.5;entryY=1;")
e(sfn,sup,"5 Invoke  /  6 Recommendation","startArrow=block;startFill=1;exitX=1;exitY=0.25;entryX=0;entryY=0.5;",[(870,175),(870,210)])
for a in (val,cli,eli,adj):
    e(sup,a,"","exitX=0;exitY=0.5;entryX=0;entryY=0.5;",None)
cells_fix=[]
e(sup,mem,"","startArrow=block;startFill=1;exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e(rt,fm,"LLM inference","exitX=0.5;exitY=0;entryX=0;entryY=0.5;",[(1055,138),(1440,138),(1440,160)])
e(fm,grd,"","endArrow=none;dashed=1;")
e(cli,kb,"Retrieve (RAG)","exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e(rt,gw,"","exitX=1;exitY=0.72;entryX=0;entryY=0.5;")
e(idn,gw,"authZ","dashed=1;")
e(gw,tools,"","exitX=0.5;exitY=1;entryX=0.8;entryY=0;")
e(tools,aur,"SQL","exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e(kb,aoss,"","exitX=1;exitY=0.5;entryX=0.5;entryY=0;")
e(s3kb,kb,"Ingest","exitX=0.5;exitY=0;entryX=0;entryY=0.75;",[(1505,357)])
e(sfn,sns,"7 Needs review","exitX=0.75;exitY=1;entryX=1;entryY=0.5;",[(750,240),(790,240),(790,690)])
e(sns,exm,"Notify","exitX=0;exitY=0.5;entryX=0.5;entryY=0;",[(65,690)])
e(exm,amp,"","exitX=1;exitY=0.5;entryX=0;entryY=0.5;")
e(amp,apigw2); e(apigw2,lrev)
e(lrev,sfn,"8 Approve / override (task token)","exitX=1;exitY=0.5;entryX=1;entryY=0.75;",[(850,790),(850,205)])

# ---- legend
legend=("<b>MVP flow</b><br><br>"
"<b>1</b> Provider signs in to the Amplify Provider Portal (Cognito), uploads CMS-1500 + evidence via pre-signed URL, and tracks claim status.<br><br>"
"<b>2</b> S3 Object Created event on EventBridge starts one Step Functions execution per packet.<br><br>"
"<b>3</b> Bedrock Data Automation splits, classifies and extracts fields with confidence scores.<br><br>"
"<b>4</b> BDA completion event resumes the workflow; claim case JSON is assembled.<br><br>"
"<b>5</b> Strands Supervisor on AgentCore Runtime delegates to Validation, Eligibility, Clinical Review and Adjudication agents. Tools via AgentCore Gateway (OAuth token from AgentCore Identity); policies via Knowledge Bases on S3 Vectors.<br><br>"
"<b>6</b> Structured recommendation: APPROVE / DENY / PEND, reason codes, evidence citations, confidence.<br><br>"
"<b>7</b> Auto-finalize only if all checks pass, confidence is high and amount is under limit. All denials go to an examiner.<br><br>"
"<b>8</b> Examiner approves or overrides; decision resumes the workflow and is stored as feedback.")
v(legend,"rounded=1;arcSize=2;html=1;whiteSpace=wrap;fillColor=#F8F8F8;strokeColor=#D5DBDB;align=left;verticalAlign=top;spacing=12;fontSize=11;fontColor=#232F3E;",1720,60,320,560)
v("<b>Agentic Claims Processing (CMS-1500) - MVP</b>","text;html=1;align=left;verticalAlign=middle;fontSize=16;fontColor=#232F3E;",1720,20,320,30)

body="".join(cells)
open(sys.argv[1],"w").write('<mxfile host="drawio"><diagram name="MVP Architecture" id="mvp"><mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="2100" pageHeight="1100" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'+body+'</root></mxGraphModel></diagram></mxfile>')
