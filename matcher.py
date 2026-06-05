def match_dsl(candidate_dsl, job_dsl):
    c = set(candidate_dsl.lower().split())
    j = set(job_dsl.lower().split())
    return len(c & j)