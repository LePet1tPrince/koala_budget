<template>
  <section class="app-card">
    <div class="flex flex-col space-y-4 lg:flex-row lg:space-x-4 lg:space-y-0">
        <div class="basis-1/3 grow-0 shrink-0">
            <img class="img-fluid" alt="Nothing Here" :src="staticFiles.undraw_empty"/>
        </div>
        <div class="flex-1">
            <h1 class="text-3xl font-bold mb-2">No Employees Yet!</h1>
            <h2 class="text-xl mb-1">Create your first employee below to get started.</h2>
            <p>
                <a class="btn btn-primary my-3" v-on:click="$emit('add-employee')">
                    <span class="w-6 h-6 inline-flex justify-center items-center"><Icon name="plus" class-name="inline-block shrink-0 w-4 h-4" /></span>
                    <span>Create Employee</span>
                </a>
            </p>
        </div>
    </div>
</section>
</template>

<script>
import Icon from '../../../../common/Icon.vue';
export default {
  name: 'NoData',
  components: {
    Icon
  },
  props: {
    static_files: Object
  },
}

</script>
