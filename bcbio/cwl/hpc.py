"""Setup configurations for running on HPC clusters with CWL.

Contains support for setting up configuration inputs for Cromwell.
"""
import os

def create_cromwell_config(args, work_dir):
    """Prepare a cromwell configuration within the current working directory.
    """
    docker_attrs = ["String? docker", "String? docker_user"]
    cwl_attrs = ["Int? cpuMin", "Int? cpuMax", "Int? memoryMin", "Int? memoryMax", "String? outDirMin",
                 "String? outDirMax", "String? tmpDirMin", "String? tmpDirMax"]
    out_file = os.path.join(work_dir, "bcbio-cromwell.conf")
    std_args = {"docker_attrs": "" if args.no_container else "\n        ".join(docker_attrs),
                "submit_docker": 'submit-docker: ""' if args.no_container else "",
                "cwl_attrs": "\n        ".join(cwl_attrs),
                "filesystem": FILESYSTEM_CONFIG}
    cl_args, conf_args, scheduler = _args_to_cromwell(args)
    conf_args.update(std_args)
    main_config = {"hpc": (HPC_CONFIGS[scheduler] % conf_args) if scheduler else "",
                   "work_dir": work_dir}
    main_config.update(std_args)
    # Local run always seems to need docker set because of submit-docker in default configuration
    # Can we unset submit-docker based on configuration so it doesn't inherit?
    #main_config["docker_attrs"] = "\n        ".join(docker_attrs)
    with open(out_file, "w") as out_handle:
        out_handle.write(CROMWELL_CONFIG % main_config)
    return out_file

def args_to_cromwell_cl(args):
    """Convert input bcbio arguments into cromwell command line arguments.
    """
    cl_args, conf_args, scheduler = _args_to_cromwell(args)
    return cl_args

def _args_to_cromwell(args):
    """Convert input arguments into cromwell inputs for config and command line.
    """
    scheduler_map = {"sge": "SGE", "slurm": "SLURM", "lsf": "LSF"}
    default_config = {"slurm": {"timelimit": "1-00:00", "account": ""},
                      "sge": {"memtype": "mem_type", "pename": "smp"},
                      "lsf": {},
                      "torque": {"walltime": "1-00:00", "account": ""},
                      "pbspro": {"walltime": "1-00:00", "account": "",
                                 "cpu_and_mem": "-l select=1:ncpus=${cpu}:mem=${memory_mb}mb"}}
    prefixes = {("account", "slurm"): "-A ", ("account", "pbspro"): "-A "}
    custom = {("noselect", "pbspro"): ("cpu_and_mem", "-l ncpus=${cpu} -l mem=${memory_mb}mb")}
    cl = ["-Dload-control.memory-threshold-in-mb=1"]
    # HPC scheduling
    if args.scheduler:
        if args.scheduler not in default_config:
            raise ValueError("Scheduler not yet supported by Cromwell: %s" % args.scheduler)
        if not args.queue:
            raise ValueError("Need to set queue (-q) for running with an HPC scheduler")
        config = default_config[args.scheduler]
        cl.append("-Dbackend.default=%s" % args.scheduler.upper())
        config["queue"] = args.queue
        for rs in args.resources:
            for r in rs.split(";"):
                parts = r.split("=")
                if len(parts) == 2:
                    key, val = parts
                    config[key] = prefixes.get((key, args.scheduler), "") + val
                elif len(parts) == 1 and (parts[0], args.scheduler) in custom:
                    key, val = custom[(parts[0], args.scheduler)]
                    config[key] = val
        return cl, config, args.scheduler
    # Local multicore runs
    # Avoid overscheduling jobs for local runs by limiting concurrent jobs
    # Longer term would like to keep these within defined core window
    else:
        return ["-Dbackend.providers.Local.config.concurrent-job-limit=1"] + cl, {}, None


FILESYSTEM_CONFIG = """
      filesystems {
        local {
          localization: ["soft-link"]
          caching {
            duplication-strategy: ["soft-link"]
            hashing-strategy: "path"
          }
        }
      }
"""

CROMWELL_CONFIG = """
include required(classpath("application"))

system {
  workflow-restart = true
}
call-caching {
  enabled = true
}

database {
  profile = "slick.jdbc.HsqldbProfile$"
  db {
    driver = "org.hsqldb.jdbcDriver"
    url = "jdbc:hsqldb:file:%(work_dir)s/persist/metadata;shutdown=false;hsqldb.tx=mvcc"
    connectionTimeout = 20000
  }
}

backend {
  providers {
    Local {
      config {
        runtime-attributes = \"\"\"
        Int? cpu
        Int? memory_mb
        %(docker_attrs)s
        %(cwl_attrs)s
        \"\"\"
        %(submit_docker)s
        %(filesystem)s
      }
    }
%(hpc)s
  }
}
"""

HPC_CONFIGS = {
"slurm": """
    SLURM {
      actor-factory = "cromwell.backend.impl.sfs.config.ConfigBackendLifecycleActorFactory"
      config {
        runtime-attributes = \"\"\"
        Int cpu = 1
        Int memory_mb = 2048
        String queue = "%(queue)s"
        String timelimit = "%(timelimit)s"
        String account = "%(account)s"
        %(docker_attrs)s
        %(cwl_attrs)s
        \"\"\"
        submit = \"\"\"
            sbatch -J ${job_name} -D ${cwd} -o ${out} -e ${err} -t ${timelimit} -p ${queue} \
            ${"--cpus-per-task=" + cpu} --mem=${memory_mb} ${account} \
            --wrap "/usr/bin/env bash ${script}"
        \"\"\"
        kill = "scancel ${job_id}"
        check-alive = "squeue -j ${job_id}"
        job-id-regex = "Submitted batch job (\\\\d+).*"
        %(filesystem)s
      }
    }
""",
"sge": """
    SGE {
      actor-factory = "cromwell.backend.impl.sfs.config.ConfigBackendLifecycleActorFactory"
      config {
        runtime-attributes = \"\"\"
        Int cpu = 1
        Int memory_mb = 2048
        String queue = "%(queue)s"
        String pename = "%(pename}s"
        String memtype = "%(memtype)s"
        %(docker_attrs)s
        %(cwl_attrs)s
        \"\"\"
        submit = \"\"\"
        qsub -V -w w -j y -N ${job_name} -wd ${cwd} \
        -o ${out} -e ${err} -q ${queue} \
        -pe ${pename} ${cpu} ${"-l " + mem_type + "=" + memory_mb + "m"} \
        /usr/bin/env bash ${script}
        \"\"\"
        kill = "qdel ${job_id}"
        check-alive = "qstat -j ${job_id}"
        job-id-regex = "(\\\\d+)"
        %(filesystem)s
      }
    }
""",
"pbspro": """
    PBSPRO {
      actor-factory = "cromwell.backend.impl.sfs.config.ConfigBackendLifecycleActorFactory"
      config {
        runtime-attributes = \"\"\"
        Int cpu = 1
        Int memory_mb = 2048
        String queue = "%(queue)s"
        String account = "%(account)s"
        String walltime = "%(walltime)s"
        %(docker_attrs)s
        %(cwl_attrs)s
        \"\"\"
        submit = \"\"\"
        qsub -V -l wd -N ${job_name} -o ${out} -e ${err} -q ${queue} -l walltime=${walltime} \
        %(cpu_and_mem)s \
        -- /usr/bin/env bash ${script}
        \"\"\"
        kill = "qdel ${job_id}"
        check-alive = "qstat -j ${job_id}"
        job-id-regex = "(\\\\d+)"
        %(filesystem)s
      }
    }

""",
"torque": """
    TORQUE {
      actor-factory = "cromwell.backend.impl.sfs.config.ConfigBackendLifecycleActorFactory"
      config {
        runtime-attributes = \"\"\"
        Int cpu = 1
        Int memory_mb = 2048
        String queue = "%(queue)s"
        String account = "%(account)s"
        String walltime = "%(walltime)s"
        %(docker_attrs)s
        %(cwl_attrs)s
        \"\"\"
        submit = \"\"\"
        qsub -V -l wd -N ${job_name} -o ${out} -e ${err} -q ${queue} \
        -l nodes=1:ppn=${cpu} -l mem=${memory_mb}mb -l walltime=${walltime} \
        -- /usr/bin/env bash ${script}
        \"\"\"
        kill = "qdel ${job_id}"
        check-alive = "qstat -j ${job_id}"
        job-id-regex = "(\\\\d+)"
        %(filesystem)s
      }
    }
"""
}
