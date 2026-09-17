<template>
  <tr>
    <td>{{ employee.name }}</td>
    <td>{{ employee.department }}</td>
    <td class="text-right">{{ formattedSalary }}</td>
    <td class="flex space-x-1 justify-end">
      <a class="btn btn-outline" v-on:click="editEmployee">
        <span class="w-6 h-6 inline-flex justify-center items-center"><Icon name="edit" class-name="inline-block shrink-0 w-4 h-4" /></span>
        <span class="hidden md:inline-block">Edit</span>
      </a>
      <a class="btn btn-outline btn-error" v-on:click="deleteEmployee">
        <span class="w-6 h-6 inline-flex justify-center items-center"><Icon name="times" class-name="inline-block shrink-0 w-4 h-4" /></span>
        <span class="hidden md:inline-block">Delete</span>
      </a>
    </td>
  </tr>
</template>

<script>
import Icon from '../../../../common/Icon.vue';

export default {
  name: 'EmployeeTableRow',
  components: {
    Icon
  },
  props: {
    employee: Object,
    client: Object,
  },
  computed: {
    formattedSalary: function () {
      const formatter = new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
      });
      return formatter.format(this.employee.salary);
    }
  },
  methods: {
    editEmployee: function () {
      this.$emit('edit-employee', this.employee);
    },
    deleteEmployee: function () {
      this.$emit('delete-employee', this.employee);
    },
  }
};
</script>

<style scoped>
</style>
