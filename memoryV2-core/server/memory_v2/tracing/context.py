"""Chain Trace Context 传递机制"""
from contextvars import ContextVar
from typing import Optional
from .types import ChainTrace, WriteTrace, RetrievalTrace, GenerationTrace

# 全局 ContextVar
_chain_trace: ContextVar[Optional[ChainTrace]] = ContextVar('chain_trace', default=None)

def get_chain_trace() -> Optional[ChainTrace]:
    """获取当前请求的 ChainTrace"""
    return _chain_trace.get()

def set_chain_trace(trace: ChainTrace):
    """设置当前请求的 ChainTrace"""
    _chain_trace.set(trace)

def init_chain_trace() -> ChainTrace:
    """初始化 ChainTrace"""
    trace = ChainTrace()
    set_chain_trace(trace)
    return trace

def get_or_create_write_trace() -> WriteTrace:
    """获取或创建 WriteTrace"""
    trace = get_chain_trace()
    if trace is None:
        # 如果没有 ChainTrace，创建一个独立的 WriteTrace
        return WriteTrace()
    
    if trace.write is None:
        trace.write = WriteTrace()
    
    return trace.write

def get_or_create_retrieval_trace() -> RetrievalTrace:
    """获取或创建 RetrievalTrace"""
    trace = get_chain_trace()
    if trace is None:
        return RetrievalTrace()
    
    if trace.retrieval is None:
        trace.retrieval = RetrievalTrace()
    
    return trace.retrieval

def get_or_create_generation_trace() -> GenerationTrace:
    """获取或创建 GenerationTrace"""
    trace = get_chain_trace()
    if trace is None:
        return GenerationTrace()
    
    if trace.generation is None:
        trace.generation = GenerationTrace()
    
    return trace.generation
