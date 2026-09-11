export const viewLabels = {home:'首页',discover:'岗位发现',feedback:'反馈与建议',runs:'运行记录'};
export function resolveView(hash, current='home'){if(hash==='#main')return Object.hasOwn(viewLabels,current)?current:'home';const view=hash.replace(/^#/,'');return Object.hasOwn(viewLabels,view)?view:'home';}
export function safeLink(value){try{const u=new URL(value);const host=u.hostname.toLowerCase().replace(/\.$/,'');if(!['https:','http:'].includes(u.protocol)||u.username||u.password||/[\s\\\x00-\x1f]/.test(value)||host==='localhost'||host.endsWith('.local')||host.endsWith('.internal')||host.endsWith('.localhost')||!host.includes('.')||/^(127\.|10\.|192\.168\.|169\.254\.|0\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)||(u.port&&!['80','443'].includes(u.port)))return null;return u.href;}catch{return null;}}
export function filterJobs(jobs,filters){
 const terms=(filters.query||'').trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
 return jobs.filter(j=>{const hay=[j.title,j.company,j.location,...(j.tags||[]),j.description].join(' ').toLocaleLowerCase();return terms.every(t=>hay.includes(t))&&(!filters.location||j.location===filters.location)&&(!filters.workplaces?.length||filters.workplaces.includes(j.workplace))&&(!filters.sources?.length||filters.sources.some(s=>(j.source_ids||[j.source_id]).includes(s)))&&(!filters.status||filters.status==='all'||j.status===filters.status);}).sort((a,b)=>filters.sort==='company'?a.company.localeCompare(b.company,'zh-CN'):(Date.parse(filters.sort==='published'?b.published_at:b.first_seen_at)||0)-(Date.parse(filters.sort==='published'?a.published_at:a.first_seen_at)||0)||a.id.localeCompare(b.id));
}

export const issueTemplates={jobs:'01-job-request.yml',feature:'02-feature-request.yml',source:'03-source-request.yml',problem:'04-problem-report.yml'};
export function issueUrl(kind, values={}){
 const base='https://github.com/BillShiyaoZhang/job-hunting/issues/new';
 if(!Object.hasOwn(issueTemplates,kind))return `${base}/choose`;
 const url=new URL(base);url.searchParams.set('template',issueTemplates[kind]);
 const allowed={jobs:['roles','location','context'],feature:['context'],source:['context'],problem:['url','context']};
 for(const key of allowed[kind])if(typeof values[key]==='string'&&values[key].trim())url.searchParams.set(key,values[key].slice(0,key==='url'?1000:500));
 return url.href;
}
export function jobSources(jobs){const sources=new Map();for(const job of jobs)if(job.source_id&&!sources.has(job.source_id))sources.set(job.source_id,{id:job.source_id,name:job.source_name||job.source_id});return [...sources.values()].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));}
