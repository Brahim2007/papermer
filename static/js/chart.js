$.ajax({
  type:"GET",
  url:`/get_readers/${id}/`,
  success:function (data){
    var colors = []
    let academic = data["readers"]
    let sub = data["readers_by_sub"]

    Object.values(academic).map(()=>{
      colors.push(getRandomColor())
    })
    let config = {
      type:'pie',
      data:{
        labels:Object.keys(academic),
        datasets:[
          {
          data:Object.values(academic),
          label:"Dataset 1",
          backgroundColor:colors
          }
        ],
      },
      options: {
        responsive: true,
        legend: {
          position: 'bottom',
        },
        animation: {
          animateScale: true,
          animateRotate: true
        }
      }
    }

    colors = []
    Object.values(sub).map(()=>{
      colors.push(getRandomColor())
    })
    var ctx = document.getElementById('chartContainer').getContext('2d');
    window.academic_pie = new Chart(ctx, config);

    let config_sub = {
      type:'pie',
      data:{
        labels:Object.keys(sub),
        datasets:[
          {
          data:Object.values(sub),
          label:"Dataset 1",
          backgroundColor:colors
          }
        ],
      },
      options: {
        responsive: true,
        legend: {
          position: 'bottom',
        },
        animation: {
          animateScale: true,
          animateRotate: true
        }
      }
    }
    var ctx = document.getElementById('sub_chart').getContext('2d');
    window.academic_pie = new Chart(ctx, config_sub);


  }
})

function getRandomColor() {
  var letters = '0123456789ABCDEF';
  var color = '#';
  for (var i = 0; i < 6; i++) {
    color += letters[Math.floor(Math.random() * 16)];
  }
  return color;
}
