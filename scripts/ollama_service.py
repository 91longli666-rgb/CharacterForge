"""Project service entry point; works with PowerShell script execution disabled."""
from pathlib import Path
import argparse,json,os,sys
ROOT=Path(os.environ.get('CF_PROJECT_ROOT',Path(__file__).resolve().parents[1])).resolve()
CODE_ROOT=Path(os.environ.get('CF_CODE_ROOT',Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(CODE_ROOT/'src'))
from characterforge.llm.ollama_service import PortableOllama
def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('start','stop','status'));args=parser.parse_args()
    try:
        service=PortableOllama(ROOT);value=getattr(service,args.action)()
        print(json.dumps(value,ensure_ascii=True));return 0
    except Exception as error:
        print('Project Ollama: '+str(error),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
